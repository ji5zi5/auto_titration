#!/usr/bin/env python3
"""Validate MicroPixeler's own grayToTemp against Analyzer CSV matrices.

This probe does not fit a CSV lookup.  It:
  1. parses a Mini2 radiometric JPEG with HIKMICRO Analyzer's MicroPixeler DLL,
  2. asks TakedMaterialAnalyzControl::grayToTemp(raw_gray) for each unique raw
     uint16 value from the extracted LPLD matrix,
  3. compares the SDK-returned integer temperature (and likely /10 Celsius) to
     the Analyzer-exported CSV only as validation evidence.

Run with Windows Python from the project mirror.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import json
import math
import os
import struct
from pathlib import Path


DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
WIDTH = 256
HEIGHT = 192
KEEP = []


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


def proc(dll: ctypes.CDLL, name: bytes) -> int:
    k32 = ctypes.windll.kernel32
    k32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    k32.GetProcAddress.restype = ctypes.c_void_p
    addr = k32.GetProcAddress(dll._handle, name)
    if not addr:
        raise RuntimeError(f"missing export {name!r}")
    return int(addr)


def sstr(s: str) -> StdString:
    b = s.encode("utf-8")
    st = StdString()
    if len(b) < 16:
        ctypes.memmove(ctypes.addressof(st), b + b"\0", len(b) + 1)
        st.size = len(b)
        st.capacity = 15
    else:
        keep = ctypes.create_string_buffer(b + b"\0")
        KEEP.append(keep)
        ptr = ctypes.c_void_p(ctypes.addressof(keep))
        ctypes.memmove(ctypes.addressof(st), ctypes.byref(ptr), ctypes.sizeof(ptr))
        st.size = len(b)
        st.capacity = len(b)
    return st


def fake_ctrl(initial: int = 1_000_000) -> int:
    ctrl = ctypes.create_string_buffer(0x40)
    vt = (ctypes.c_void_p * 4)()
    ctypes.c_void_p.from_buffer(ctrl, 0).value = ctypes.addressof(vt)
    ctypes.c_uint32.from_buffer(ctrl, 8).value = initial
    ctypes.c_uint32.from_buffer(ctrl, 12).value = initial
    KEEP.extend([ctrl, vt])
    return ctypes.addressof(ctrl)


def hx(v) -> str | None:
    return hex(int(v)) if v else None


def read_raw_u16(path: Path) -> list[int]:
    data = path.read_bytes()
    if len(data) < WIDTH * HEIGHT * 2:
        raise ValueError(f"raw file too small: {len(data)}")
    return list(struct.unpack("<" + "H" * (WIDTH * HEIGHT), data[: WIDTH * HEIGHT * 2]))


def read_csv_matrix(path: Path) -> list[float]:
    last = None
    for enc in ("utf-8-sig", "cp949", "euc-kr", "latin1"):
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError as exc:
            last = exc
    else:
        raise last or RuntimeError("cannot decode CSV")
    vals: list[float] = []
    for row in csv.reader(text.splitlines()):
        # Analyzer matrix CSV has a header row:
        #   축 X/Y,0,1,2,...,255
        # and then 192 data rows:
        #   y,temp0,temp1,...,temp255
        if row and row[0].strip().lower() in {"축 x/y", "x/y"}:
            continue
        nums = []
        for cell in row:
            try:
                nums.append(float(cell.strip()))
            except Exception:
                pass
        if len(nums) >= WIDTH + 1:
            tail = nums[1 : WIDTH + 1]
            if tail and -100 <= min(tail) and max(tail) <= 1000:
                vals.extend(tail)
    if len(vals) < WIDTH * HEIGHT:
        raise ValueError(f"CSV matrix too small: {len(vals)}")
    return vals[: WIDTH * HEIGHT]


def validate(pred: list[float], truth: list[float]) -> dict[str, object]:
    n = min(len(pred), len(truth))
    diffs = [pred[i] - truth[i] for i in range(n) if math.isfinite(pred[i])]
    if not diffs:
        return {"count": 0}
    worst_idx = sorted(range(n), key=lambda i: abs(pred[i] - truth[i]), reverse=True)[:16]
    return {
        "count": len(diffs),
        "mae": sum(abs(d) for d in diffs) / len(diffs),
        "max_abs": max(abs(d) for d in diffs),
        "bias": sum(diffs) / len(diffs),
        "exact_0p1_match_rate": sum(abs(d) < 1e-9 for d in diffs) / len(diffs),
        "gt_0p05": sum(abs(d) > 0.05 for d in diffs),
        "gt_0p10": sum(abs(d) > 0.10 for d in diffs),
        "worst": [
            {"idx": i, "x": i % WIDTH, "y": i // WIDTH, "pred": pred[i], "csv": truth[i], "diff": pred[i] - truth[i]}
            for i in worst_idx
        ],
    }


def parse_material(pix: ctypes.CDLL, jpeg: Path, flag: bool):
    st = sstr(str(jpeg))
    vec = StdVector(None, None, None)
    out_type = ctypes.c_uint32(0)
    out_bool = ctypes.c_bool(False)
    fn = ctypes.CFUNCTYPE(
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_bool),
        ctypes.POINTER(StdString),
        ctypes.POINTER(StdVector),
        ctypes.c_bool,
    )(
        proc(
            pix,
            b"?parseRadiometricsJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEAIAEA_NAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@5@_N@Z",
        )
    )
    mat = fn(ctypes.byref(out_type), ctypes.byref(out_bool), ctypes.byref(st), ctypes.byref(vec), flag)
    return mat, {"flag": flag, "out_type": int(out_type.value), "out_bool": bool(out_bool.value)}


def create_material_q(pix: ctypes.CDLL, jpeg: Path, material_type: int, flag: bool):
    st = sstr(str(jpeg))
    vec = StdVector(None, None, None)
    fn = ctypes.CFUNCTYPE(
        ctypes.c_void_p, ctypes.c_int32, ctypes.POINTER(StdString), ctypes.POINTER(StdVector), ctypes.c_bool
    )(
        proc(
            pix,
            b"?createMaterialQ@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@W4MaterialType@iVMS4800@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@7@_N@Z",
        )
    )
    mat = fn(material_type, ctypes.byref(st), ctypes.byref(vec), flag)
    return mat, {"factory": "createMaterialQ", "material_type": material_type, "flag": flag}


def make_control(pix: ctypes.CDLL):
    create_default = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(
        proc(pix, b"?createDefault@AnalyzerBuilderManager@MICROPIXELER@@SA?AV?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@XZ")
    )
    ctor = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(SharedPtr))(
        proc(pix, b"??0TakedMaterialAnalyzControl@MICROPIXELER@@QEAA@V?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@@Z")
    )
    builder = SharedPtr()
    create_default(ctypes.byref(builder))
    obj = ctypes.create_string_buffer(0x5000)
    KEEP.append(obj)
    ctor(ctypes.byref(obj), ctypes.byref(builder))
    return obj, {"builder_ptr": hx(builder.ptr), "builder_ctrl": hx(builder.ctrl)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, required=True)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("data/mini2_micropixeler_gray_matrix_validate"))
    args = ap.parse_args(argv)

    orig = Path.cwd()
    jpeg = args.jpeg.resolve()
    raw_path = args.raw.resolve()
    csv_path = args.csv.resolve()
    out_dir = args.out if args.out.is_absolute() else orig / args.out

    raws = read_raw_u16(raw_path)
    truth = read_csv_matrix(csv_path)

    add_dll_dir(args.dll_dir)
    pix = ctypes.WinDLL(str(args.dll_dir / "MicroPixeler_Release_x64.dll"))
    os.chdir(str(orig))

    temp_analyze = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(SharedPtr))(
        proc(pix, b"?tempAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z")
    )
    img_analyze_syn = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(SharedPtr))(
        proc(pix, b"?imgAnalyzeSyn@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z")
    )
    rule_area_measure = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(SharedPtr))(
        proc(pix, b"?ruleAreaMeasure@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z")
    )
    gray_to_temp = ctypes.CFUNCTYPE(
        ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(SharedPtr), ctypes.c_int32
    )(proc(pix, b"?grayToTemp@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NAEAHV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@H@Z"))

    report: dict[str, object] = {"jpeg": str(jpeg), "raw": str(raw_path), "csv": str(csv_path), "cases": []}
    unique_raw = sorted(set(raws))

    sequences = [
        ("none", []),
        ("tempAnalyze", [temp_analyze]),
        ("imgAnalyzeSyn", [img_analyze_syn]),
        ("imgAnalyzeSyn_tempAnalyze", [img_analyze_syn, temp_analyze]),
        ("tempAnalyze_ruleAreaMeasure", [temp_analyze, rule_area_measure]),
    ]

    material_cases = []
    for flag in (False, True):
        material_cases.append(("parseRadiometricsJPEG",) + parse_material(pix, jpeg, flag))
    for mt in (0, 1, 2, 3, 4, 8, 9):
        for flag in (False, True):
            try:
                material_cases.append((f"createMaterialQ_type{mt}",) + create_material_q(pix, jpeg, mt, flag))
            except Exception as exc:
                report["cases"].append({"parser": f"createMaterialQ_type{mt}", "flag": flag, "exception": repr(exc)})

    for parser_name, mat, meta in material_cases:
        for seq_name, funcs in sequences:
            rec: dict[str, object] = {"parser": parser_name, "parse": meta, "mat": hx(mat), "sequence": seq_name}
            if not mat:
                report["cases"].append(rec)
                continue
            ctrl, ctrl_meta = make_control(pix)
            rec.update(ctrl_meta)
            sp = SharedPtr(ctypes.c_void_p(mat), ctypes.c_void_p(fake_ctrl()))
            call_results = []
            for fn in funcs:
                try:
                    call_results.append(bool(fn(ctypes.byref(ctrl), ctypes.byref(sp))))
                except Exception as exc:
                    call_results.append(repr(exc))
            rec["analysis_calls"] = call_results
            conv: dict[int, int | None] = {}
            ok_count = 0
            for g in unique_raw:
                out = ctypes.c_int32(-2147483648)
                ok = bool(gray_to_temp(ctypes.byref(ctrl), ctypes.byref(out), ctypes.byref(sp), int(g)))
                if ok:
                    ok_count += 1
                    conv[g] = int(out.value)
                else:
                    conv[g] = None
            rec["unique_raw_count"] = len(unique_raw)
            rec["grayToTemp_ok_count"] = ok_count
            # HIK SDK temperature integers are usually tenths of degrees.
            pred = [float("nan") if conv[g] is None else conv[g] / 10.0 for g in raws]
            rec["validation_out_div10"] = validate(pred, truth)
            rec["sample_mapping"] = [
                {"raw": g, "sdk_int": conv[g], "sdk_div10": None if conv[g] is None else conv[g] / 10.0}
                for g in unique_raw[:20]
            ]
            report["cases"].append(rec)

    out_dir.mkdir(parents=True, exist_ok=True)
    op = out_dir / (jpeg.stem + "_micropixeler_gray_matrix_validate.json")
    op.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:30000])
    print("saved:", op)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
