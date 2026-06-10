#!/usr/bin/env python3
"""Extract HIKMICRO Analyzer/MicroJPEG IRDataInfo temperature matrix.

This is a reverse-engineering validation probe, not a CSV fitting script.
It asks the installed HIKMICRO DLLs to parse a radiometric JPEG, reads the
StandardRImage::irDataInfo structure, and optionally validates the resulting
temperature matrix against the Analyzer-exported CSV.
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


class BareBlock(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.c_void_p),
        ("size", ctypes.c_uint32),
        ("pad", ctypes.c_uint32),
    ]


class Coord(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]


def add_dll_dir(p: Path) -> None:
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(p))
    ctypes.windll.kernel32.SetDllDirectoryW(str(p))
    os.chdir(str(p))


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


def u64_at(addr: int, off: int = 0) -> int:
    return struct.unpack("<Q", ctypes.string_at(addr + off, 8))[0]


def u32s_at(addr: int, n: int = 0x80) -> list[int]:
    raw = ctypes.string_at(addr, n)
    return [struct.unpack_from("<I", raw, i)[0] for i in range(0, n, 4)]


def f32s_at(addr: int, n: int = 0x80) -> list[float]:
    raw = ctypes.string_at(addr, n)
    return [struct.unpack_from("<f", raw, i)[0] for i in range(0, n, 4)]


def ptr_rva(ptr: int, base: int, limit: int = 0x3000000) -> str | None:
    return hex(ptr - base) if ptr and base <= ptr < base + limit else None


def csv_matrix(path: Path, width: int) -> list[float]:
    last = None
    for enc in ("utf-8-sig", "cp949", "euc-kr", "latin1"):
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError as exc:
            last = exc
    else:
        raise last or RuntimeError("cannot decode csv")
    vals: list[float] = []
    for row in csv.reader(text.splitlines()):
        nums = []
        for cell in row:
            try:
                nums.append(float(cell.strip()))
            except Exception:
                pass
        if len(nums) >= width:
            tail = nums[-width:]
            if tail and max(tail) <= 500:
                vals.extend(tail)
    return vals


def validate(pred: list[float], truth: list[float]) -> dict[str, object]:
    n = min(len(pred), len(truth))
    finite = [i for i in range(n) if math.isfinite(pred[i])]
    if not finite:
        return {"count": 0}
    diffs = [pred[i] - truth[i] for i in finite]
    rounded_diffs = [round(pred[i], 1) - truth[i] for i in finite]
    worst = sorted(finite, key=lambda i: abs(pred[i] - truth[i]), reverse=True)[:20]
    return {
        "count": len(finite),
        "mae": sum(abs(d) for d in diffs) / len(diffs),
        "max_abs": max(abs(d) for d in diffs),
        "bias": sum(diffs) / len(diffs),
        "rounded_0p1_match_rate": sum(abs(d) < 1e-9 for d in rounded_diffs) / len(rounded_diffs),
        "rounded_0p1_mae": sum(abs(d) for d in rounded_diffs) / len(rounded_diffs),
        "gt0p05": sum(abs(d) > 0.05 for d in diffs),
        "gt0p10": sum(abs(d) > 0.10 for d in diffs),
        "worst": [
            {
                "idx": i,
                "y": i // 256,
                "x": i % 256,
                "pred": pred[i],
                "csv": truth[i],
                "diff": pred[i] - truth[i],
            }
            for i in worst
        ],
    }


def read_irdata_matrix(ir_ptr: int) -> dict[str, object]:
    width = ctypes.c_int32.from_address(ir_ptr + 0).value
    height = ctypes.c_int32.from_address(ir_ptr + 4).value
    data_ptr = u64_at(ir_ptr, 0x08)
    # IRDataInfo is used by MicroTA::TempMatrix as:
    #   [0]=width, [4]=height, [8]=float* temperature_data, [0x18]=byte length.
    byte_len = u64_at(ir_ptr, 0x18)
    rec: dict[str, object] = {
        "ir_ptr": hx(ir_ptr),
        "u32_0_128": u32s_at(ir_ptr, 0x80),
        "f32_0_128": f32s_at(ir_ptr, 0x80),
        "width": width,
        "height": height,
        "data_ptr": hx(data_ptr),
        "byte_len": byte_len,
        "expected_byte_len": width * height * 4 if width > 0 and height > 0 else None,
    }
    vals: list[float] = []
    if width > 0 and height > 0 and data_ptr and byte_len >= width * height * 4:
        raw = ctypes.string_at(data_ptr, width * height * 4)
        vals = list(struct.unpack("<" + "f" * (width * height), raw))
        rec.update(
            {
                "temp_c_count": len(vals),
                "temp_c_min": min(vals),
                "temp_c_max": max(vals),
                "temp_c_first32": vals[:32],
            }
        )
    else:
        rec["temp_c_count"] = 0
    rec["_vals"] = vals
    return rec


def tempmatrix_values(ta: ctypes.CDLL, ir_ptr: int, width: int, height: int, limit: int = 0) -> dict[str, object]:
    ctor = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(ta, b"??0TempMatrix@MicroSDK@@QEAA@AEBUIRDataInfo@1@@Z")
    )
    dtor = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(
        get_proc(ta, b"??1TempMatrix@MicroSDK@@QEAA@XZ")
    )
    temp_int = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(Coord))(
        get_proc(ta, b"?temp@TempMatrix@MicroSDK@@QEAA_NAEAHAEBUCoordinate2D@2@@Z")
    )
    temp_float = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.POINTER(Coord))(
        get_proc(ta, b"?temp@TempMatrix@MicroSDK@@QEAA_NAEAMAEBUCoordinate2D@2@@Z")
    )
    obj = ctypes.create_string_buffer(0x40)
    out: dict[str, object] = {}
    try:
        rv = ctor(ctypes.byref(obj), ctypes.c_void_p(ir_ptr))
        out["ctor_ret"] = hx(rv)
        out["obj_qwords"] = [hex(struct.unpack_from("<Q", obj.raw, i)[0]) for i in range(0, 0x18, 8)]
        total = width * height
        n = total if limit <= 0 else min(limit, total)
        ints: list[int] = []
        floats: list[float] = []
        ok_i = 0
        ok_f = 0
        for idx in range(n):
            c = Coord(idx % width, idx // width)
            oi = ctypes.c_int32(-2147483648)
            of = ctypes.c_float(float("nan"))
            if temp_int(ctypes.byref(obj), ctypes.byref(oi), ctypes.byref(c)):
                ok_i += 1
            if temp_float(ctypes.byref(obj), ctypes.byref(of), ctypes.byref(c)):
                ok_f += 1
            ints.append(int(oi.value))
            floats.append(float(of.value))
        out.update(
            {
                "count": n,
                "temp_int_ok": ok_i,
                "temp_float_ok": ok_f,
                "temp_int_first32": ints[:32],
                "temp_float_first32": floats[:32],
                "temp_float_min": min([v for v in floats if math.isfinite(v)], default=float("nan")),
                "temp_float_max": max([v for v in floats if math.isfinite(v)], default=float("nan")),
                "_float_vals": floats,
            }
        )
    finally:
        try:
            dtor(ctypes.byref(obj))
        except Exception as exc:
            out["dtor_exception"] = repr(exc)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, required=True)
    ap.add_argument("--csv", type=Path)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=Path, default=Path("data/mini2_microjpeg_irdata_tempmatrix_probe"))
    args = ap.parse_args(argv)

    jpeg_abs = args.jpeg.resolve()
    csv_abs = args.csv.resolve() if args.csv else None
    out_dir = args.out.resolve() if not args.out.is_absolute() else args.out

    add_dll_dir(args.dll_dir)
    mj = ctypes.WinDLL(str(args.dll_dir / "MicroJPEG_Release_x64.dll"))
    ta = ctypes.WinDLL(str(args.dll_dir / "MicroTA_Release_x64.dll"))
    mj_base = int(mj._handle)

    create_auto = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock))(
        get_proc(mj, b"?createImage@MicroSDK@@YAPEAVBaseImage@1@AEBUBareBlock@1@@Z")
    )
    create_std = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock))(
        get_proc(mj, b"?createStandardRImage@ImageFactory@MicroSDK@@SAPEAVStandardRImage@2@AEBUBareBlock@2@@Z")
    )
    create_v2 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock))(
        get_proc(mj, b"?createMicroRImageV2@ImageFactory@MicroSDK@@SAPEAVMicroRImageV2@2@AEBUBareBlock@2@@Z")
    )
    type_fn = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(
        get_proc(mj, b"?type@BaseImage@MicroSDK@@QEBA?AW4FileType@2@XZ")
    )
    std_irdata = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(mj, b"?irDataInfo@StandardRImage@MicroSDK@@QEBAAEBUIRDataInfo@2@XZ")
    )

    data = jpeg_abs.read_bytes()
    keep = ctypes.create_string_buffer(data, len(data))
    block = BareBlock(ctypes.cast(keep, ctypes.c_void_p), len(data), 0)

    report: dict[str, object] = {
        "jpeg": str(jpeg_abs),
        "csv": str(csv_abs) if csv_abs else None,
        "dll_dir": str(args.dll_dir),
        "objects": [],
    }

    for name, maker in [("createImage_auto", create_auto), ("createStandardRImage", create_std), ("createMicroRImageV2", create_v2)]:
        rec: dict[str, object] = {"name": name}
        try:
            ptr = int(maker(ctypes.byref(block)) or 0)
            rec["ptr"] = hx(ptr)
            if ptr:
                vptr = u64_at(ptr)
                rec["vptr"] = hx(vptr)
                rec["vptr_rva_microjpeg"] = ptr_rva(vptr, mj_base)
                try:
                    rec["type"] = int(type_fn(ctypes.c_void_p(ptr)))
                except Exception as exc:
                    rec["type_exception"] = repr(exc)
                try:
                    ir_ptr = int(std_irdata(ctypes.c_void_p(ptr)) or 0)
                    rec["standard_irdata_ptr"] = hx(ir_ptr)
                    if ir_ptr:
                        ir = read_irdata_matrix(ir_ptr)
                        vals = ir.pop("_vals")
                        rec["irdata"] = ir
                        if vals and csv_abs and csv_abs.exists():
                            truth = csv_matrix(csv_abs, int(ir["width"]))
                            rec["irdata_validation_vs_csv"] = validate(vals, truth)
                        if vals:
                            tm = tempmatrix_values(ta, ir_ptr, int(ir["width"]), int(ir["height"]), args.limit)
                            tm_vals = tm.pop("_float_vals", [])
                            rec["tempmatrix"] = tm
                            if tm_vals and csv_abs and csv_abs.exists():
                                truth = csv_matrix(csv_abs, int(ir["width"]))[: len(tm_vals)]
                                rec["tempmatrix_validation_vs_csv"] = validate(tm_vals, truth)
                except Exception as exc:
                    rec["irdata_exception"] = repr(exc)
        except Exception as exc:
            rec["exception"] = repr(exc)
        report["objects"].append(rec)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{jpeg_abs.stem}_irdata_tempmatrix_probe.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        "jpeg": str(jpeg_abs),
        "objects": [
            {
                "name": r.get("name"),
                "ptr": r.get("ptr"),
                "vptr_rva": r.get("vptr_rva_microjpeg"),
                "type": r.get("type"),
                "ir": {
                    k: (r.get("irdata") or {}).get(k)
                    for k in ("width", "height", "byte_len", "temp_c_count", "temp_c_min", "temp_c_max", "temp_c_first32")
                },
                "ir_validation": r.get("irdata_validation_vs_csv"),
                "tm": {
                    k: (r.get("tempmatrix") or {}).get(k)
                    for k in ("count", "temp_int_ok", "temp_float_ok", "temp_int_first32", "temp_float_first32")
                },
                "tm_validation": r.get("tempmatrix_validation_vs_csv"),
                "error": r.get("exception") or r.get("irdata_exception"),
            }
            for r in report["objects"]
        ],
        "out": str(out_path),
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2)[:20000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
