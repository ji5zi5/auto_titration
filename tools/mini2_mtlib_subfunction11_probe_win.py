#!/usr/bin/env python3
"""Probe MTlib_OL.MT_SubFunction with its hidden 5th-argument output ABI.

Disassembly plus calling tests show the output pointer is the 5th user
argument ([entry_rsp+0x28], observed as [rbp+0xc0] after the prolog). This
script calls MT_SubFunction with 7 ctypes arguments so case 1 can generate/copy
the gray->temperature table and case 2 can write a full-frame output buffer.
No CSV fitting is used; CSV is validation only.
"""
from __future__ import annotations

import argparse
import ctypes
import csv
import json
import math
import os
import struct
import sys
from pathlib import Path

THIS = Path(__file__).resolve()
TOOLS = THIS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from mini2_mtlib_api_probe_win import (  # noqa: E402
    DLL_DIR_DEFAULT,
    HEIGHT,
    WIDTH,
    add_dll_dir,
    buf_from_bytes,
    encode_type1_value,
    extract_blocks,
    get_sdmp_block,
    inspect_handle,
    make_desc,
    radiometric_params_from_jpeg,
    radiometric_type1_pairs,
    raw_path_for,
    tag1_internal_reflected_c,
)

PIXELS = WIDTH * HEIGHT


def csv_flat(path: Path) -> list[float]:
    text = None
    for enc in ["utf-8-sig", "cp949", "euc-kr", "latin1"]:
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            pass
    if text is None:
        return []
    out: list[float] = []
    for row in csv.reader(text.splitlines()):
        nums=[]
        for c in row:
            try: nums.append(float(c.strip()))
            except Exception: pass
        if len(nums) >= WIDTH:
            xs = nums[-WIDTH:]
            if max(xs) <= 150:
                out.extend(xs)
    return out


def type1_payload(key: int, value: int) -> bytes:
    return struct.pack("<II", int(key), int(value) & 0xffffffff)


def measurement_config8_block(*, emissivity: float, reflected_c: float, distance_m: float) -> bytes:
    """Build the 0xd8-byte MT_SetConfig(type=8) measurement/environment block.

    Disassembly evidence: MT_SetConfig type 8 copies a 0xd8-byte block into
    handle+0x1e0, and MT_SubFunction case 2 copies handle+0x1e0+0x38.. into
    its per-frame measurement records.  Earlier probes wrote these fields into
    the case-2 input struct, but case 2 does not read them there.
    """

    block = bytearray(0xD8)
    for base in [0x38, 0x38 + 0x24, 0x38 + 0x48, 0x38 + 0x6C]:
        struct.pack_into("<f", block, base + 0x14, float(emissivity))
        struct.pack_into("<f", block, base + 0x18, float(reflected_c))
        struct.pack_into("<f", block, base + 0x1C, float(distance_m))
    return bytes(block)


def setup_handle(
    dll,
    jpeg: Path,
    *,
    radiometric_profile: str = "none",
    set_key_raw: list[tuple[int, int, str]] | None = None,
    set_tag50_type12: bool = False,
):
    MT_GetMemSize = dll.MT_GetMemSize
    MT_GetMemSize.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    MT_GetMemSize.restype = ctypes.c_int
    MT_Create = dll.MT_Create
    MT_Create.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    MT_Create.restype = ctypes.c_int
    MT_SetConfig = dll.MT_SetConfig
    MT_SetConfig.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    MT_SetConfig.restype = ctypes.c_int

    blocks = extract_blocks(jpeg)
    raw = raw_path_for(jpeg).read_bytes()
    raw_frame = raw + blocks["tag1"]
    params = ctypes.create_string_buffer(0x20)
    struct.pack_into("<IIII", params, 0, WIDTH, HEIGHT, 1, 1)
    backing, desc, _ = make_desc()
    MT_GetMemSize(ctypes.byref(params), ctypes.byref(desc))
    backing, desc, desc_info = make_desc()
    handle = ctypes.c_void_p()
    cret = MT_Create(ctypes.byref(params), ctypes.byref(desc), ctypes.byref(handle))
    h = int(handle.value or 0)
    if cret != 0 or not h:
        raise RuntimeError(f"MT_Create failed ret={cret} handle={h}")
    keep = [backing, desc, params]
    calib_param_type = struct.unpack_from("<I", blocks["tag519"], 8)[0]
    setconfig = []
    config_items: list[tuple[int, bytes, str]] = [
        (6, blocks["tag519"], "APP2 tag519"),
        (1, type1_payload(15, calib_param_type), f"key15 calib_param_type={calib_param_type}"),
    ]
    radiometric_params = None
    if radiometric_profile != "none":
        radiometric_params = radiometric_params_from_jpeg(jpeg)
        for key, value, label in radiometric_type1_pairs(radiometric_params, radiometric_profile):
            encoded = encode_type1_value(key, value)
            config_items.append((1, type1_payload(key, encoded), f"{label}; value={value} encoded={encoded}"))
    for key, raw_value, label in set_key_raw or []:
        config_items.append((1, type1_payload(key, raw_value), label))
    if set_tag50_type12:
        config_items.append((12, get_sdmp_block(jpeg, 0xE3, 50), "APP3 tag50 -> MT_SetConfig type12"))
    config_items.append((7, raw_frame, "raw+tag1"))

    for typ, data, name in config_items:
        b = buf_from_bytes(data)
        keep.append(b)
        ret = MT_SetConfig(handle, typ, ctypes.cast(b, ctypes.c_void_p), len(data))
        setconfig.append({"type": typ, "name": name, "ret": ret})
    return handle, h, keep, blocks, raw, setconfig, desc_info, radiometric_params


def nonzero_summary(data: bytes, unit: str) -> dict[str, object]:
    if unit == "u16":
        vals = struct.unpack("<" + "H" * (len(data)//2), data)
    elif unit == "f32":
        vals = struct.unpack("<" + "f" * (len(data)//4), data)
    else:
        vals = tuple(data)
    nz = [(i, v) for i, v in enumerate(vals) if v != 0]
    return {
        "unit": unit,
        "count": len(vals),
        "nonzero_count": len(nz),
        "first32": list(vals[:32]),
        "first_nonzero": nz[:20],
        "min": min(vals) if vals else None,
        "max": max(vals) if vals else None,
    }


def validate(pred: list[float], truth: list[float]) -> dict[str, object]:
    n=min(len(pred),len(truth))
    finite=[i for i in range(n) if math.isfinite(pred[i])]
    if not finite: return {"count":0}
    diffs=[pred[i]-truth[i] for i in finite]
    rd=[round(pred[i],1)-truth[i] for i in finite]
    return {"count":len(finite),"mae":sum(abs(d) for d in diffs)/len(diffs),"max_abs":max(abs(d) for d in diffs),"bias":sum(diffs)/len(diffs),"rounded_0p1_match_rate":sum(1 for d in rd if abs(d)<1e-9)/len(rd),"rounded_0p1_mae":sum(abs(d) for d in rd)/len(rd),"gt0p05":sum(1 for d in diffs if abs(d)>0.05),"gt0p1":sum(1 for d in diffs if abs(d)>0.1)}


def main(argv=None) -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, required=True)
    ap.add_argument("--variant", choices=["raw", "raw_frame", "struct_raw_tag1", "struct_raw_zero"], default="raw")
    ap.add_argument(
        "--radiometric-profile",
        choices=["none", "basic", "with_window", "with_expert", "all_known"],
        default="none",
        help="Apply MT_SetConfig(type=1) key/value pairs from embedded Radiometric.json before MT_SubFunction.",
    )
    ap.add_argument(
        "--set-key-raw",
        action="append",
        default=[],
        metavar="KEY=INT",
        help="Extra raw MT_SetConfig(type=1) key/value pair. No unit encoding is applied.",
    )
    ap.add_argument("--emissivity", type=float, default=7946/8192)
    ap.add_argument("--reflected-c", type=float, default=None)
    ap.add_argument("--distance-m", type=float, default=1.0)
    ap.add_argument(
        "--config8-measurement-block",
        action="store_true",
        help="Also set MT_SetConfig(type=8) with the 0xd8 measurement block that MT_SubFunction case 2 actually reads.",
    )
    ap.add_argument(
        "--set-tag50-type12",
        action="store_true",
        help="Also set MT_SetConfig(type=12) with APP3 tag50 (256 uint32 / width*4 bytes) before raw+tag1.",
    )
    ap.add_argument(
        "--set-tag50-type12-after-raw",
        action="store_true",
        help="Set MT_SetConfig(type=12) with APP3 tag50 again after raw+tag1 setup, to test order-sensitive table rebuilds.",
    )
    ap.add_argument("--out", type=Path, default=Path("data/mini2_mtlib_subfunction11_probe"))
    args=ap.parse_args(argv)

    raw_pairs: list[tuple[int, int, str]] = []
    for item in args.set_key_raw:
        if "=" not in item:
            raise SystemExit(f"bad --set-key-raw {item!r}; expected KEY=INT")
        k_s, v_s = item.split("=", 1)
        key = int(k_s, 0)
        raw_value = int(v_s, 0)
        raw_pairs.append((key, raw_value, f"manual raw key{key} value={raw_value}"))

    add_dll_dir(args.dll_dir)
    dll=ctypes.WinDLL(str(args.dll_dir/"MTlib_OL.dll"))
    MT_SubFunction=dll.MT_SubFunction
    # 5th-argument output ABI. Only arg1-4 and arg11 are proven for case1/case2 here.
    MT_SubFunction.argtypes=[ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int,
                             ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    MT_SubFunction.restype=ctypes.c_int

    handle,h,keep,blocks,raw,setconfig,desc_info,radiometric_params=setup_handle(
        dll,
        args.jpeg,
        radiometric_profile=args.radiometric_profile,
        set_key_raw=raw_pairs,
        set_tag50_type12=args.set_tag50_type12,
    )
    tag1=blocks["tag1"]
    effective_reflected_c = args.reflected_c if args.reflected_c is not None else tag1_internal_reflected_c(tag1)

    if args.config8_measurement_block:
        cfg8 = measurement_config8_block(
            emissivity=args.emissivity,
            reflected_c=effective_reflected_c,
            distance_m=args.distance_m,
        )
        cfg8_buf = buf_from_bytes(cfg8)
        keep.append(cfg8_buf)
        mt_set_config = dll.MT_SetConfig
        mt_set_config.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        mt_set_config.restype = ctypes.c_int
        ret_cfg8 = mt_set_config(handle, 8, ctypes.cast(cfg8_buf, ctypes.c_void_p), len(cfg8))
        setconfig.append(
            {
                "type": 8,
                "name": "measurement block: per-record emissivity/reflected/distance for MT_SubFunction case2",
                "len": len(cfg8),
                "ret": ret_cfg8,
            }
        )
    if args.set_tag50_type12_after_raw:
        tag50 = get_sdmp_block(args.jpeg, 0xE3, 50)
        tag50_buf = buf_from_bytes(tag50)
        keep.append(tag50_buf)
        mt_set_config = dll.MT_SetConfig
        mt_set_config.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        mt_set_config.restype = ctypes.c_int
        ret_tag50_after = mt_set_config(handle, 12, ctypes.cast(tag50_buf, ctypes.c_void_p), len(tag50))
        setconfig.append(
            {
                "type": 12,
                "name": "APP3 tag50 -> MT_SetConfig type12 after raw+tag1",
                "len": len(tag50),
                "ret": ret_tag50_after,
            }
        )
    raw_buf=ctypes.create_string_buffer(raw, len(raw)); keep.append(raw_buf)
    raw_frame=raw+tag1
    raw_frame_buf=ctypes.create_string_buffer(raw_frame, len(raw_frame)); keep.append(raw_frame_buf)
    tag1_buf=ctypes.create_string_buffer(tag1, len(tag1)); keep.append(tag1_buf)
    dummy_table=ctypes.create_string_buffer(0x10000); keep.append(dummy_table)

    if args.variant=="raw":
        in_ptr=ctypes.cast(raw_buf, ctypes.c_void_p); in_len=len(raw)
    elif args.variant=="raw_frame":
        in_ptr=ctypes.cast(raw_frame_buf, ctypes.c_void_p); in_len=len(raw_frame)
    else:
        s=ctypes.create_string_buffer(0xD0)
        struct.pack_into("<Q", s, 0, ctypes.addressof(raw_buf))
        if args.variant=="struct_raw_tag1":
            struct.pack_into("<Q", s, 8, ctypes.addressof(tag1_buf))
        struct.pack_into("<Q", s, 0x10, ctypes.addressof(dummy_table))
        # Fill copied 0x90-ish measurement block with sane defaults: emissivity,
        # reflected, distance at offsets matching MT_Process point fields.
        for base in [0x38, 0x38+0x24, 0x38+0x48, 0x38+0x6c]:
            if base+0x20 < len(s):
                struct.pack_into("<f", s, base+0x14, args.emissivity)
                struct.pack_into("<f", s, base+0x18, effective_reflected_c)
                struct.pack_into("<f", s, base+0x1c, args.distance_m)
        keep.append(s)
        in_ptr=ctypes.cast(s, ctypes.c_void_p); in_len=len(s)

    out_table=ctypes.create_string_buffer(0x20000)
    out_struct=ctypes.create_string_buffer(0x20)
    struct.pack_into("<QQ", out_struct, 0, 0, ctypes.addressof(out_table))
    keep += [out_table, out_struct]
    ret1=MT_SubFunction(handle,1,in_ptr,in_len,ctypes.cast(out_struct, ctypes.c_void_p),0,None)
    table_bytes=out_table.raw

    # Case2 full frame. Try u16 and f32 interpretations of the same output.
    in2=ctypes.create_string_buffer(0xD0)
    struct.pack_into("<Q", in2, 0, ctypes.addressof(raw_buf))
    struct.pack_into("<Q", in2, 8, ctypes.addressof(tag1_buf))
    struct.pack_into("<Q", in2, 0x10, ctypes.addressof(out_table))
    for base in [0x38, 0x38+0x24, 0x38+0x48, 0x38+0x6c]:
        if base+0x20 < len(in2):
            struct.pack_into("<f", in2, base+0x14, args.emissivity)
            struct.pack_into("<f", in2, base+0x18, effective_reflected_c)
            struct.pack_into("<f", in2, base+0x1c, args.distance_m)
    keep.append(in2)
    out2=ctypes.create_string_buffer(PIXELS*4)
    keep.append(out2)
    ret2=MT_SubFunction(handle,2,ctypes.cast(in2,ctypes.c_void_p),len(in2),ctypes.cast(out2,ctypes.c_void_p),PIXELS*4,None)
    raw_out=out2.raw
    vals_u16=list(struct.unpack("<"+"H"*PIXELS, raw_out[:PIXELS*2]))
    vals_f32=list(struct.unpack("<"+"f"*PIXELS, raw_out[:PIXELS*4]))

    truth=csv_flat(args.jpeg.with_name(args.jpeg.stem+"_이미지.csv"))
    # Try common output scales. This is validation only; conversion data came from DLL.
    pred_candidates={
        "u16_div10": [v/10.0 for v in vals_u16],
        "u16_div100": [v/100.0 for v in vals_u16],
        "f32": vals_f32,
    }
    validation={k: validate(v, truth) for k,v in pred_candidates.items()} if truth else {}

    rep={
        "jpeg":str(args.jpeg),"variant":args.variant,
        "radiometric_profile": args.radiometric_profile,
        "radiometric_params_from_jpeg": radiometric_params,
        "expert_params_for_case2_block": {
            "emissivity": args.emissivity,
            "reflected_c": effective_reflected_c,
            "distance_m": args.distance_m,
        },
        "config8_measurement_block_enabled": bool(args.config8_measurement_block),
        "tag50_type12_enabled": bool(args.set_tag50_type12),
        "tag50_type12_after_raw_enabled": bool(args.set_tag50_type12_after_raw),
        "setconfig":setconfig,"desc_info":desc_info,
        "handle": inspect_handle(h),
        "tag1_internal_reflected_c": tag1_internal_reflected_c(tag1),
        "ret1_case1":ret1,
        "out_struct_u64":[hex(struct.unpack_from('<Q',out_struct.raw,i)[0]) for i in range(0,0x20,8)],
        "table_summary_u16":nonzero_summary(table_bytes[:0x10000],"u16"),
        "table_summary_f32":nonzero_summary(table_bytes[:0x10000],"f32"),
        "ret2_case2":ret2,
        "out2_summary_u16":nonzero_summary(raw_out[:PIXELS*2],"u16"),
        "out2_summary_f32":nonzero_summary(raw_out[:PIXELS*4],"f32"),
        "validation_vs_csv":validation,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    suffix = args.variant if args.radiometric_profile == "none" and not args.set_key_raw else f"{args.variant}_{args.radiometric_profile}_{len(raw_pairs)}keys"
    if args.config8_measurement_block:
        suffix += "_cfg8"
    if args.set_tag50_type12:
        suffix += "_tag50t12"
    if args.set_tag50_type12_after_raw:
        suffix += "_tag50t12after"
    out=args.out/f"{args.jpeg.stem}_{suffix}_subfunction11.json"
    out.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({"jpeg":str(args.jpeg),"variant":args.variant,"ret1":ret1,"ret2":ret2,"table_u16":rep['table_summary_u16'],"out2_u16":rep['out2_summary_u16'],"out2_f32":rep['out2_summary_f32'],"validation":validation,"out":str(out)},ensure_ascii=False,indent=2)[:20000])
    return 0

if __name__=='__main__':
    raise SystemExit(main())
