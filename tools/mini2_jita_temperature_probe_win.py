#!/usr/bin/env python3
"""Use HIKMICRO Analyzer's MicroJITA SDK exports to convert Mini2 gray to temp.

This is the non-lookup path we are looking for:

    createFromJPEG(void*& ctx, BareBlock const& jpeg)
    getRawDataInfo(RawDataInfo& out, void* ctx)
    grayToTemperature(int& outTemp, uint16 gray, void* ctx)
    destroy(void* ctx)

It never reads the Analyzer-exported temperature CSV while converting. Optional
CSV validation only compares the SDK output against the CSV after conversion.
"""

from __future__ import annotations

import argparse
import ctypes
import csv
import json
import os
import statistics
import struct
from pathlib import Path


DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
WIDTH = 256
HEIGHT = 192
PIXELS = WIDTH * HEIGHT


class BareBlock(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.c_void_p),
        ("size", ctypes.c_uint32),
        ("pad", ctypes.c_uint32),
    ]


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
    block = BareBlock(ctypes.cast(buf, ctypes.c_void_p), len(data), 0)
    return buf, block


def load_csv_matrix(path: Path) -> list[float]:
    last_exc: Exception | None = None
    for encoding in ("utf-8-sig", "cp949", "euc-kr", "utf-16"):
        try:
            rows: list[list[str]] = []
            with path.open("r", encoding=encoding, newline="") as f:
                rows = list(csv.reader(f))
            axis = None
            for i, row in enumerate(rows):
                if row and row[0].strip() == "축 X/Y":
                    axis = i
                    break
            if axis is None:
                continue
            vals: list[float] = []
            for row in rows[axis + 1 :]:
                if not row or not row[0].strip():
                    continue
                try:
                    int(float(row[0]))
                except ValueError:
                    continue
                vals.extend(float(cell.strip()) for cell in row[1:] if cell.strip())
            break
        except UnicodeError as exc:
            last_exc = exc
    else:
        raise last_exc or UnicodeError("could not decode CSV")
    if len(vals) != PIXELS:
        raise ValueError(f"{path} yielded {len(vals)} numeric cells, expected {PIXELS}")
    return vals


def load_raw_u16(path: Path) -> list[int]:
    data = path.read_bytes()
    if len(data) < PIXELS * 2:
        raise ValueError(f"raw file too small: {path} {len(data)}")
    return list(struct.unpack("<" + "H" * PIXELS, data[: PIXELS * 2]))


def summarize_errors(pred: list[float], truth: list[float]) -> dict[str, object]:
    err = [p - t for p, t in zip(pred, truth)]
    abs_err = [abs(x) for x in err]
    rounded_match = sum(1 for p, t in zip(pred, truth) if round(p, 1) == round(t, 1))
    within_005 = sum(1 for x in abs_err if x <= 0.0500001)
    within_01 = sum(1 for x in abs_err if x <= 0.1000001)
    return {
        "count": len(pred),
        "mae": sum(abs_err) / len(abs_err),
        "rmse": (sum(x * x for x in err) / len(err)) ** 0.5,
        "max_abs_error": max(abs_err),
        "mean_error": sum(err) / len(err),
        "rounded_0p1_match": rounded_match,
        "within_0p05": within_005,
        "within_0p1": within_01,
        "first_mismatches": [
            {"index": i, "sdk_c": pred[i], "csv_c": truth[i], "err": err[i]}
            for i in range(len(pred))
            if round(pred[i], 1) != round(truth[i], 1)
        ][:20],
    }


def decode_scale(raw_ints: list[int], truth: list[float] | None) -> tuple[float, str]:
    # HIKMICRO temperature APIs often use centi- or deci-C integers. Infer the
    # scale only from comparing against optional CSV validation data; this does
    # not change the conversion itself.
    if truth is None:
        return 100.0, "default_centidegree_without_csv"
    candidates = [(1.0, "integer_C"), (10.0, "deci_C"), (100.0, "centi_C"), (1000.0, "milli_C")]
    best = min(
        candidates,
        key=lambda item: sum(abs((x / item[0]) - t) for x, t in zip(raw_ints[: min(len(raw_ints), 5000)], truth[: min(len(raw_ints), 5000)])),
    )
    return best


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, required=True)
    ap.add_argument("--raw-u16", type=Path, required=True)
    ap.add_argument("--csv", type=Path)
    ap.add_argument("--out", type=Path, default=Path("data/mini2_jita_temperature_probe"))
    ap.add_argument("--empty-context", action="store_true", help="Use MicroSDK::createEmptyJPEG instead of createFromJPEG")
    args = ap.parse_args(argv)

    add_dll_dir(args.dll_dir)
    dll = ctypes.WinDLL(str(args.dll_dir / "MicroJITA_Release_x64.dll"))

    create_from_jpeg = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(BareBlock))(
        get_proc(dll, b"?createFromJPEG@MicroSDK@@YA_NAEAPEAXAEBUBareBlock@1@@Z")
    )
    create_empty_jpeg = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_void_p))(
        get_proc(dll, b"?createEmptyJPEG@MicroSDK@@YA_NAEAPEAX@Z")
    )
    destroy = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p)(
        get_proc(dll, b"?destroy@MicroSDK@@YA_NPEAX@Z")
    )
    get_raw_info = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(dll, b"?getRawDataInfo@MicroSDK@@YA_NAEAURawDataInfo@1@QEAX@Z")
    )
    set_raw_info = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(dll, b"?setRawDataInfo@MicroSDK@@YA_NAEBURawDataInfo@1@PEAX@Z")
    )
    gray_to_temp = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_uint16, ctypes.c_void_p)(
        get_proc(dll, b"?grayToTemperature@MicroSDK@@YA_NAEAHGQEAX@Z")
    )
    temperature_to_gray = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p)(
        get_proc(dll, b"?temperatureToGray@MicroSDK@@YA_NAEAGHQEAX@Z")
    )
    get_temp_device = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(dll, b"?getTempDeviceConfigParams@MicroSDK@@YA_NAEAUTempDeviceConfigParams@1@QEAX@Z")
    )
    get_temp_measure = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(dll, b"?getTempMeasurementParams@MicroSDK@@YA_NAEAUTempMeasurementParameters@1@QEAX@Z")
    )
    format_quick = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(BareBlock))(
        get_proc(dll, b"?formatQuick@MicroSDK@@YA?AW4JPEGFormat@1@AEBUBareBlock@1@@Z")
    )
    format_ctx = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(
        get_proc(dll, b"?format@MicroSDK@@YA?AW4JPEGFormat@1@QEAX@Z")
    )
    last_error = ctypes.CFUNCTYPE(ctypes.c_uint32)(
        get_proc(dll, b"?lastError@MicroSDK@@YAIXZ")
    )

    jpeg_buf, jpeg_block = make_block(args.jpeg.read_bytes())
    quick_format = int(format_quick(ctypes.byref(jpeg_block)))
    ctx = ctypes.c_void_p()
    ok = bool(create_empty_jpeg(ctypes.byref(ctx))) if args.empty_context else bool(create_from_jpeg(ctypes.byref(ctx), ctypes.byref(jpeg_block)))
    if not ok or not ctx.value:
        raise RuntimeError(f"context create failed empty={args.empty_context} ok={ok} ctx={ctx.value} formatQuick={quick_format} lastError={last_error()}")

    try:
        raw = load_raw_u16(args.raw_u16)
        raw_bytes = args.raw_u16.read_bytes()[: PIXELS * 2]
        raw_buf = ctypes.create_string_buffer(raw_bytes)
        # RawDataInfo layout observed from MicroJPEG::UnCompresser:
        # u32 width, u32 height, u32 format, padding, ptr at +0x10, size at +0x20.
        injected_raw_info = ctypes.create_string_buffer(0x80)
        struct.pack_into("<III", injected_raw_info, 0, WIDTH, HEIGHT, 14)
        struct.pack_into("<Q", injected_raw_info, 0x10, ctypes.addressof(raw_buf))
        struct.pack_into("<I", injected_raw_info, 0x20, len(raw_bytes))
        set_raw_ok = bool(set_raw_info(ctypes.byref(injected_raw_info), ctx))
        error_after_set_raw = int(last_error())

        raw_info = ctypes.create_string_buffer(0x400)
        raw_info_ok = bool(get_raw_info(ctypes.byref(raw_info), ctx))
        error_after_raw_info = int(last_error())
        temp_device_buf = ctypes.create_string_buffer(0x800)
        temp_measure_buf = ctypes.create_string_buffer(0x800)
        try:
            temp_device_ok = bool(get_temp_device(ctypes.byref(temp_device_buf), ctx))
            temp_device_error = int(last_error())
            temp_device_exc = None
        except Exception as exc:
            temp_device_ok = False
            temp_device_error = int(last_error())
            temp_device_exc = repr(exc)
        try:
            temp_measure_ok = bool(get_temp_measure(ctypes.byref(temp_measure_buf), ctx))
            temp_measure_error = int(last_error())
            temp_measure_exc = None
        except Exception as exc:
            temp_measure_ok = False
            temp_measure_error = int(last_error())
            temp_measure_exc = repr(exc)
        ctx_format = int(format_ctx(ctx))
        raw_info_prefix_u32 = [
            int.from_bytes(raw_info.raw[i : i + 4], "little") for i in range(0, 0x80, 4)
        ]

        raw_int_temps: list[int] = []
        failed = 0
        for g in raw:
            out = ctypes.c_int32(-2_147_483_648)
            if bool(gray_to_temp(ctypes.byref(out), ctypes.c_uint16(g), ctx)):
                raw_int_temps.append(int(out.value))
            else:
                if failed == 0:
                    first_gray_error = int(last_error())
                failed += 1
                raw_int_temps.append(-2_147_483_648)

        truth = load_csv_matrix(args.csv) if args.csv else None
        scale, scale_name = decode_scale(raw_int_temps, truth)
        temps_c = [x / scale for x in raw_int_temps]

        # Check inverse API at representative converted temperatures.
        inv_samples = []
        for idx in [0, 1, 2, 10, 100, 1000, 10_000, 20_000, 40_000, PIXELS - 1]:
            t_int = raw_int_temps[idx]
            gout = ctypes.c_uint16(0)
            inv_ok = bool(temperature_to_gray(ctypes.byref(gout), ctypes.c_int32(t_int), ctx))
            inv_samples.append(
                {
                    "index": idx,
                    "raw_gray": raw[idx],
                    "temp_int": t_int,
                    "temp_c": t_int / scale,
                    "inverse_ok": inv_ok,
                    "inverse_gray": int(gout.value),
                }
            )

        report = {
            "jpeg": str(args.jpeg),
            "raw_u16": str(args.raw_u16),
            "csv": str(args.csv) if args.csv else None,
            "sdk_exports": [
                "createFromJPEG(void*& ctx, BareBlock const& jpeg)",
                "getRawDataInfo(RawDataInfo& out, void* ctx)",
                "grayToTemperature(int& outTemp, uint16 gray, void* ctx)",
                "temperatureToGray(uint16& outGray, int temp, void* ctx)",
                "destroy(void* ctx)",
            ],
            "createFromJPEG_ok": ok,
            "ctx": hex(ctx.value),
            "formatQuick": quick_format,
            "format_ctx": ctx_format,
            "last_error_after_getRawDataInfo": error_after_raw_info,
            "setRawDataInfo_injected_ok": set_raw_ok,
            "last_error_after_setRawDataInfo": error_after_set_raw,
            "last_error_after_first_grayToTemperature_fail": locals().get("first_gray_error"),
            "getRawDataInfo_ok": raw_info_ok,
            "raw_info_prefix_u32": raw_info_prefix_u32,
            "getTempDeviceConfigParams_ok": temp_device_ok,
            "last_error_after_getTempDeviceConfigParams": temp_device_error,
            "getTempDeviceConfigParams_exception": temp_device_exc,
            "temp_device_prefix_u32": [int.from_bytes(temp_device_buf.raw[i:i+4], "little") for i in range(0, 160, 4)],
            "getTempMeasurementParams_ok": temp_measure_ok,
            "last_error_after_getTempMeasurementParams": temp_measure_error,
            "getTempMeasurementParams_exception": temp_measure_exc,
            "temp_measure_prefix_u32": [int.from_bytes(temp_measure_buf.raw[i:i+4], "little") for i in range(0, 160, 4)],
            "gray_to_temperature_failed_pixels": failed,
            "temp_int_range": [min(raw_int_temps), max(raw_int_temps)],
            "inferred_scale": scale,
            "inferred_scale_name": scale_name,
            "temp_c_range": [min(temps_c), max(temps_c)],
            "temp_c_mean": statistics.fmean(temps_c),
            "inverse_samples": inv_samples,
            "validation": summarize_errors(temps_c, truth) if truth else None,
            "sample_first_32": [
                {"raw": raw[i], "temp_int": raw_int_temps[i], "temp_c": temps_c[i], "csv_c": truth[i] if truth else None}
                for i in range(min(32, len(raw)))
            ],
        }

        args.out.mkdir(parents=True, exist_ok=True)
        stem = args.jpeg.stem
        json_path = args.out / f"{stem}_jita_temperature_probe.json"
        csv_path = args.out / f"{stem}_jita_temperature_matrix.csv"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            for y in range(HEIGHT):
                row = [f"{temps_c[y * WIDTH + x]:.4f}" for x in range(WIDTH)]
                w.writerow(row)
        print(json.dumps(report, ensure_ascii=False, indent=2)[:4000])
        print(f"saved_json: {json_path}")
        print(f"saved_csv: {csv_path}")
    finally:
        destroy(ctx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
