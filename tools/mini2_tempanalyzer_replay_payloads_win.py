#!/usr/bin/env python3
"""Replay HIKMICRO Analyzer TempAnalyzer payloads and call calculate(gray).

This is a reverse-engineering proof tool, not a CSV fitting tool.  It feeds
payloads captured from the official HIKMICRO Analyzer/Pixler process into the
official MicroTA_Release_x64.dll class:

    TempAnalyzer(TempInitParameters, RawDataInfo)
    setTempRange(TempRange)
    setModelConfig(MeasureModelParameters)
    setExpertConfig(MeasureExpertParams)
    calculate(int& outTemp, uint16 gray)

The exported temperature CSV is used only after conversion for validation.
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
WIDTH = 256
HEIGHT = 192
PIXELS = WIDTH * HEIGHT


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


def make_mutable(data: bytes, min_size: int = 0):
    size = max(len(data), min_size)
    buf = ctypes.create_string_buffer(size)
    ctypes.memmove(ctypes.addressof(buf), data, len(data))
    return buf


def csv_matrix(path: Path) -> list[float]:
    last_exc: Exception | None = None
    for enc in ("utf-8-sig", "cp949", "euc-kr", "latin1"):
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError as exc:
            last_exc = exc
    else:
        raise last_exc or RuntimeError(f"cannot decode {path}")
    vals: list[float] = []
    for row in csv.reader(text.splitlines()):
        nums: list[float] = []
        for cell in row:
            try:
                nums.append(float(cell.strip()))
            except Exception:
                pass
        if len(nums) >= WIDTH:
            row_vals = nums[-WIDTH:]
            if row_vals and max(row_vals) <= 150:
                vals.extend(row_vals)
    if len(vals) != PIXELS:
        raise ValueError(f"{path} yielded {len(vals)} temperature values, expected {PIXELS}")
    return vals


def raw_path_for(jpeg: Path) -> Path:
    candidates = [
        Path("data/mini2_multi_image_formula/raw") / f"{jpeg.stem}_lpld_raw_u16_256x192.bin",
        Path(r"C:\Users\Jio\Downloads\auto_titration_20260513-170048\data\mini2_multi_image_formula\raw")
        / f"{jpeg.stem}_lpld_raw_u16_256x192.bin",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"raw u16 file not found for {jpeg}")


def load_raw_u16(path: Path) -> list[int]:
    data = path.read_bytes()
    if len(data) < PIXELS * 2:
        raise ValueError(f"raw file too small: {path} ({len(data)} bytes)")
    return list(struct.unpack("<" + "H" * PIXELS, data[: PIXELS * 2]))


def validate(pred: list[float], truth: list[float]) -> dict[str, object]:
    n = min(len(pred), len(truth))
    finite = [i for i in range(n) if math.isfinite(pred[i])]
    diffs = [pred[i] - truth[i] for i in finite]
    rdiffs = [round(pred[i], 1) - truth[i] for i in finite]
    worst = sorted(finite, key=lambda i: abs(pred[i] - truth[i]), reverse=True)[:20]
    return {
        "count": len(finite),
        "mae": sum(abs(d) for d in diffs) / len(diffs) if diffs else None,
        "max_abs": max((abs(d) for d in diffs), default=None),
        "bias": sum(diffs) / len(diffs) if diffs else None,
        "rounded_0p1_mae": sum(abs(d) for d in rdiffs) / len(rdiffs) if rdiffs else None,
        "rounded_0p1_match_rate": sum(1 for d in rdiffs if abs(d) < 1e-9) / len(rdiffs) if rdiffs else None,
        "count_abs_gt_0p05": sum(1 for d in diffs if abs(d) > 0.05),
        "count_abs_gt_0p10": sum(1 for d in diffs if abs(d) > 0.10),
        "worst_pairs": [
            [i, i // WIDTH, i % WIDTH, pred[i], truth[i], pred[i] - truth[i]]
            for i in worst
        ],
    }


def u32_first(data: bytes, n: int = 64) -> list[int]:
    return [struct.unpack_from("<I", data, off)[0] for off in range(0, min(len(data), n * 4), 4)]


def infer_celsius_scale(outputs: list[int], truth: list[float] | None) -> tuple[float, str, dict[str, float]]:
    # The Analyzer trace already shows out_i32 / 8192 == displayed Celsius for
    # grayToTemperature.  Keep validation-only alternatives here to prove it.
    candidates = [
        (8192.0, "q13_celsius_from_trace"),
        (1.0, "integer_c"),
        (10.0, "deci_c"),
        (100.0, "centi_c"),
        (1000.0, "milli_c"),
    ]
    if truth is None:
        return 8192.0, "q13_celsius_from_trace", {}
    n = min(len(outputs), len(truth), 10000)
    finite = [i for i in range(n) if outputs[i] != -2147483648]
    scores: dict[str, float] = {}
    for scale, name in candidates:
        scores[name] = (
            sum(abs(outputs[i] / scale - truth[i]) for i in finite) / len(finite)
            if finite
            else float("inf")
        )
    scale, name = min(candidates, key=lambda item: scores[item[1]])
    return scale, name, scores


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--payload-dir", type=Path, required=True)
    ap.add_argument("--init", type=Path, required=True)
    ap.add_argument("--raw-info", type=Path, required=True)
    ap.add_argument("--temp-range", type=Path, required=True)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--expert", type=Path, action="append", default=[])
    ap.add_argument("--jpeg", type=Path, default=Path("data/fixtures/mini2/IR_00001.jpeg"))
    ap.add_argument("--csv", type=Path)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=Path, default=Path("data/mini2_tempanalyzer_replay_payloads"))
    args = ap.parse_args(argv)

    def pp(p: Path) -> Path:
        return p if p.is_absolute() else args.payload_dir / p

    add_dll_dir(args.dll_dir)
    dll = ctypes.WinDLL(str(args.dll_dir / "MicroTA_Release_x64.dll"))
    ctor = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(dll, b"??0TempAnalyzer@MicroSDK@@QEAA@AEBUTempInitParameters@1@AEBURawDataInfo@1@@Z")
    )
    dtor = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(
        get_proc(dll, b"??1TempAnalyzer@MicroSDK@@QEAA@XZ")
    )
    set_temp_range = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(dll, b"?setTempRange@TempAnalyzer@MicroSDK@@QEAA_NAEBUTempRange@2@@Z")
    )
    set_model = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(dll, b"?setModelConfig@TempAnalyzer@MicroSDK@@QEAA_NAEBUMeasureModelParameters@2@@Z")
    )
    set_expert = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(dll, b"?setExpertConfig@TempAnalyzer@MicroSDK@@QEAA_NAEBUMeasureExpertParams@2@@Z")
    )
    calculate = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint16)(
        get_proc(dll, b"?calculate@TempAnalyzer@MicroSDK@@QEAA_NAEAHG@Z")
    )
    last_error = ctypes.CFUNCTYPE(ctypes.c_uint32)(
        get_proc(dll, b"?lastError@MicroTA@MicroSDK@@YAIXZ")
    )

    init_b = pp(args.init).read_bytes()
    raw_b = pp(args.raw_info).read_bytes()
    range_b = pp(args.temp_range).read_bytes()
    model_b = pp(args.model).read_bytes()
    expert_bs = [pp(p).read_bytes() for p in args.expert]
    init = make_mutable(init_b, 0x1000)
    raw_info = make_mutable(raw_b, 0x1000)
    temp_range = make_mutable(range_b, 0x1000)
    model = make_mutable(model_b, 0x1000)
    experts = [make_mutable(b, 0x1000) for b in expert_bs]

    analyzer = ctypes.create_string_buffer(0x20000)
    raw_values = load_raw_u16(raw_path_for(args.jpeg))
    n = PIXELS if args.limit <= 0 else min(args.limit, PIXELS)
    truth = csv_matrix(args.csv)[:n] if args.csv and args.csv.exists() else None

    report: dict[str, object] = {
        "jpeg": str(args.jpeg),
        "payload_dir": str(args.payload_dir),
        "payloads": {
            "init": str(pp(args.init)),
            "raw_info": str(pp(args.raw_info)),
            "temp_range": str(pp(args.temp_range)),
            "model": str(pp(args.model)),
            "expert": [str(pp(p)) for p in args.expert],
        },
        "payload_u32_first": {
            "init": u32_first(init_b, 32),
            "raw_info": u32_first(raw_b, 32),
            "temp_range": u32_first(range_b, 32),
            "model": u32_first(model_b, 32),
            "expert": [u32_first(b, 32) for b in expert_bs],
        },
    }
    try:
        rv = ctor(ctypes.byref(analyzer), ctypes.byref(init), ctypes.byref(raw_info))
        report["ctor_ret"] = hex(rv) if rv else None
        report["last_after_ctor"] = int(last_error())
        report["setters"] = []
        ok_range = bool(set_temp_range(ctypes.byref(analyzer), ctypes.byref(temp_range)))
        report["setters"].append({"name": "setTempRange", "ok": ok_range, "last": int(last_error())})
        ok_model = bool(set_model(ctypes.byref(analyzer), ctypes.byref(model)))
        report["setters"].append({"name": "setModelConfig", "ok": ok_model, "last": int(last_error())})
        for i, expert in enumerate(experts):
            ok_expert = bool(set_expert(ctypes.byref(analyzer), ctypes.byref(expert)))
            report["setters"].append({"name": f"setExpertConfig[{i}]", "ok": ok_expert, "last": int(last_error())})

        outs: list[int] = []
        ok_count = 0
        first_fail = None
        for gray in raw_values[:n]:
            out = ctypes.c_int32(-2147483648)
            try:
                ok = bool(calculate(ctypes.byref(analyzer), ctypes.byref(out), ctypes.c_uint16(gray)))
            except Exception as exc:
                ok = False
                if first_fail is None:
                    first_fail = {"gray": int(gray), "exception": repr(exc), "last": int(last_error())}
            if ok:
                ok_count += 1
            elif first_fail is None:
                first_fail = {"gray": int(gray), "out": int(out.value), "last": int(last_error())}
            outs.append(int(out.value))
        scale, scale_name, scale_scores = infer_celsius_scale(outs, truth)
        temps = [x / scale if x != -2147483648 else float("nan") for x in outs]
        report["conversion"] = {
            "count": n,
            "ok_count": ok_count,
            "first_fail": first_fail,
            "out_int_minmax": [min(outs), max(outs)] if outs else None,
            "out_int_first32": outs[:32],
            "scale": scale,
            "scale_name": scale_name,
            "scale_scores_validation_only": scale_scores,
            "temp_c_minmax": [
                min((x for x in temps if math.isfinite(x)), default=float("nan")),
                max((x for x in temps if math.isfinite(x)), default=float("nan")),
            ],
            "temp_c_first32": temps[:32],
        }
        if truth:
            report["conversion"]["validation_vs_csv"] = validate(temps, truth)
    except Exception as exc:
        report["exception"] = repr(exc)
        report["last_error"] = int(last_error())
    finally:
        try:
            dtor(ctypes.byref(analyzer))
        except Exception as exc:
            report["dtor_exception"] = repr(exc)

    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / f"{args.jpeg.stem}_tempanalyzer_replay_payloads.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        "jpeg": report.get("jpeg"),
        "ctor_ret": report.get("ctor_ret"),
        "setters": report.get("setters"),
        "conversion": report.get("conversion"),
        "exception": report.get("exception"),
        "out": str(out_path),
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2)[:16000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
