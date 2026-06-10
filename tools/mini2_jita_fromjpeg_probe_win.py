#!/usr/bin/env python3
"""Use MicroJITA createFromJPEG -> grayToTemperature on HIKMICRO Mini2 JPEGs.

No CSV-derived fitting: conversion uses only the full JPEG and HIKMICRO DLLs.
CSV is loaded only after conversion to validate output units/residuals.
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

class BareBlock(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("size", ctypes.c_uint32), ("pad", ctypes.c_uint32)]


def add_dll_dir(p: Path) -> None:
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(p))
    ctypes.windll.kernel32.SetDllDirectoryW(str(p))


def get_proc(dll: ctypes.CDLL, name: bytes) -> int:
    k32 = ctypes.windll.kernel32
    k32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    k32.GetProcAddress.restype = ctypes.c_void_p
    addr = k32.GetProcAddress(dll._handle, name)
    if not addr:
        raise RuntimeError(f"missing export {name!r}")
    return int(addr)


def make_block(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return buf, BareBlock(ctypes.cast(buf, ctypes.c_void_p), len(data), 0)


def raw_path_for(jpeg: Path) -> Path:
    candidates = [
        Path('data/mini2_multi_image_formula/raw') / f"{jpeg.stem}_lpld_raw_u16_256x192.bin",
        Path('/mnt/c/Users/Jio/Downloads/auto_titration_20260513-170048/data/mini2_multi_image_formula/raw') / f"{jpeg.stem}_lpld_raw_u16_256x192.bin",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise RuntimeError(f"raw file not found for {jpeg}")


def csv_matrix(path: Path) -> list[float]:
    last = None
    for enc in ['utf-8-sig','cp949','euc-kr','latin1']:
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError as e:
            last = e
    else:
        raise last or RuntimeError('decode failed')
    rows=[]
    for row in csv.reader(text.splitlines()):
        vals=[]
        for cell in row:
            try:
                vals.append(float(cell.strip()))
            except Exception:
                pass
        if len(vals) >= WIDTH:
            vals = vals[-WIDTH:]
            if vals and max(vals) > 150:
                continue
            rows.extend(vals)
    return rows


def validation(converted: list[float], ref: list[float]) -> dict[str, object]:
    n=min(len(converted),len(ref))
    diffs=[converted[i]-ref[i] for i in range(n) if math.isfinite(converted[i])]
    rounded=[round(converted[i],1)-ref[i] for i in range(n) if math.isfinite(converted[i])]
    worst=sorted(range(n), key=lambda i: abs(converted[i]-ref[i]) if math.isfinite(converted[i]) else -1, reverse=True)[:16]
    return {
        'count': len(diffs),
        'mae': sum(abs(d) for d in diffs)/len(diffs) if diffs else None,
        'max_abs': max((abs(d) for d in diffs), default=None),
        'bias': sum(diffs)/len(diffs) if diffs else None,
        'rounded_0p1_mae': sum(abs(d) for d in rounded)/len(rounded) if rounded else None,
        'rounded_0p1_match_rate': sum(1 for d in rounded if abs(d)<1e-9)/len(rounded) if rounded else None,
        'count_abs_gt_0p05': sum(1 for d in diffs if abs(d)>0.05),
        'count_abs_gt_0p10': sum(1 for d in diffs if abs(d)>0.10),
        'worst_pairs': [[i, i//WIDTH, i%WIDTH, converted[i], ref[i], converted[i]-ref[i]] for i in worst],
    }


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--dll-dir', type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument('--jpeg', type=Path, required=True)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--out', type=Path, default=Path('data/mini2_jita_fromjpeg_probe'))
    args=ap.parse_args()
    add_dll_dir(args.dll_dir)
    dll=ctypes.WinDLL(str(args.dll_dir/'MicroJITA_Release_x64.dll'))
    create_from_jpeg=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(BareBlock))(get_proc(dll,b'?createFromJPEG@MicroSDK@@YA_NAEAPEAXAEBUBareBlock@1@@Z'))
    destroy=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p)(get_proc(dll,b'?destroy@MicroSDK@@YA_NPEAX@Z'))
    gray_to_temp=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int32), ctypes.c_uint16, ctypes.c_void_p)(get_proc(dll,b'?grayToTemperature@MicroSDK@@YA_NAEAHGQEAX@Z'))
    get_raw=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll,b'?getRawDataInfo@MicroSDK@@YA_NAEAURawDataInfo@1@QEAX@Z'))
    get_dev=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll,b'?getTempDeviceConfigParams@MicroSDK@@YA_NAEAUTempDeviceConfigParams@1@QEAX@Z'))
    get_meas=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll,b'?getTempMeasurementParams@MicroSDK@@YA_NAEAUTempMeasurementParameters@1@QEAX@Z'))
    last_error=ctypes.CFUNCTYPE(ctypes.c_uint32)(get_proc(dll,b'?lastError@MicroSDK@@YAIXZ'))

    jpg=args.jpeg.read_bytes()
    jbuf, block=make_block(jpg)
    ctx=ctypes.c_void_p()
    ok_create=bool(create_from_jpeg(ctypes.byref(ctx), ctypes.byref(block)))
    rep={'jpeg':str(args.jpeg),'create_ok':ok_create,'ctx':hex(ctx.value) if ctx.value else None,'last_error_after_create':int(last_error())}
    raw_path=raw_path_for(args.jpeg)
    raw_b=raw_path.read_bytes()
    raw_vals=list(struct.unpack('<'+'H'*(WIDTH*HEIGHT), raw_b[:WIDTH*HEIGHT*2]))
    rep['raw_path']=str(raw_path)
    rep['raw_stats']={'min':min(raw_vals),'max':max(raw_vals),'mean':sum(raw_vals)/len(raw_vals)}
    if not ok_create or not ctx.value:
        args.out.mkdir(parents=True, exist_ok=True)
        out=args.out/f'{args.jpeg.stem}_jita_fromjpeg_probe.json'
        out.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(rep,ensure_ascii=False,indent=2))
        return 2
    try:
        for label, fn, size in [('raw_info',get_raw,0x200),('temp_device',get_dev,0x400),('temp_measurement',get_meas,0x400)]:
            buf=ctypes.create_string_buffer(size)
            try:
                ok=bool(fn(ctypes.byref(buf), ctx))
                rep[label+'_ok']=ok
                rep[label+'_last_error']=int(last_error())
                rep[label+'_u32_first64']=[struct.unpack_from('<I',buf.raw,i)[0] for i in range(0,256,4)]
                rep[label+'_i32_first64']=[struct.unpack_from('<i',buf.raw,i)[0] for i in range(0,256,4)]
            except Exception as e:
                rep[label+'_exception']=repr(e)
                rep[label+'_last_error']=int(last_error())
        total=min(len(raw_vals), args.limit) if args.limit else len(raw_vals)
        outs=[]; ok_count=0; errors=[]
        for gray in raw_vals[:total]:
            out=ctypes.c_int32(-2147483648)
            ok=bool(gray_to_temp(ctypes.byref(out), ctypes.c_uint16(gray), ctx))
            ok_count += int(ok)
            if not ok and len(errors)<20:
                errors.append(int(last_error()))
            # MicroSDK temperature ints are normally deci-deg C for Mini2 analyzer exports.
            outs.append(int(out.value)/10.0 if ok else float('nan'))
        rep['convert_count']=total
        rep['gray_to_temp_ok_count']=ok_count
        rep['gray_to_temp_errors_first20']=errors
        rep['converted_c_stats']={'min':min(x for x in outs if math.isfinite(x)) if ok_count else None,
                                  'max':max(x for x in outs if math.isfinite(x)) if ok_count else None,
                                  'mean':sum(x for x in outs if math.isfinite(x))/ok_count if ok_count else None,
                                  'first16':outs[:16]}
        csvp=args.jpeg.with_name(args.jpeg.stem+'_이미지.csv')
        if csvp.exists() and ok_count:
            rep['validation_vs_csv']=validation(outs, csv_matrix(csvp))
    finally:
        try: destroy(ctx)
        except Exception: pass
    args.out.mkdir(parents=True, exist_ok=True)
    out=args.out/f'{args.jpeg.stem}_jita_fromjpeg_probe.json'
    out.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    compact={k:rep.get(k) for k in ['jpeg','create_ok','ctx','last_error_after_create','raw_stats','raw_info_ok','temp_device_ok','temp_measurement_ok','convert_count','gray_to_temp_ok_count','converted_c_stats','validation_vs_csv']}
    compact['out']=str(out)
    print(json.dumps(compact,ensure_ascii=False,indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
