#!/usr/bin/env python3
"""Convert Mini2 raw gray values through the official HIKMICRO MTlib path.

This intentionally avoids fitting exported CSV values.  It reproduces the
MT_SetConfig/MT_Process sequence observed inside HIKMICRO Analyzer/Pixler:

  MT_Create_INT(width=256, height=192, ...)
  MT_SetConfig_INT(type=6, APP2 tag519 calibration)
  MT_SetConfig_INT(type=1, official key/value parameters from JPEG metadata)
  MT_SetConfig_INT(type=189, tag1_u16[284])
  MT_SetConfig_INT(type=12, APP3 tag1 addline block)
  MT_Process_INT(type=0, point(gray, emissivity, reflected, distance))

The output at point offset +0x10 is an integer scaled by 64 °C.  This scale is
from Analyzer process evidence: e.g. output 2155 -> 33.671875 °C.
The Analyzer CSV is read only for validation after conversion.
"""
from __future__ import annotations

import argparse
import ctypes
import csv
import io
import json
import math
import os
import struct
import sys
import zipfile
from pathlib import Path


WIDTH = 256
HEIGHT = 192
PIXELS = WIDTH * HEIGHT
POINT_SIZE = 0x24
DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")

THIS = Path(__file__).resolve()
TOOLS = THIS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
from mini2_extract_rjpeg_raw_win import iter_jpeg_segments, parse_sdmp_ifd  # noqa: E402


def add_dll_dir(p: Path) -> None:
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(p))
    ctypes.windll.kernel32.SetDllDirectoryW(str(p))


def align128(x: int) -> int:
    return (x + 0x7F) & ~0x7F


def c_addr(buf) -> int:
    return ctypes.addressof(buf)


def make_desc(total_size: int = 0x600000):
    backing = ctypes.create_string_buffer(total_size + 0x400)
    base0 = align128(c_addr(backing))
    base1 = align128(base0 + 0x500 + 0x3D00)
    size0 = (base1 - base0) & ~0x7F
    size1 = ((c_addr(backing) + len(backing)) - base1) & ~0x7F
    desc = ctypes.create_string_buffer(0x40)
    struct.pack_into("<QII", desc, 0x00, base0, size0, 0x80)
    struct.pack_into("<I", desc, 0x14, 1)
    struct.pack_into("<QII", desc, 0x18, base1, size1, 0x80)
    struct.pack_into("<I", desc, 0x2C, 0)
    return backing, desc, {
        "base0": hex(base0),
        "size0": size0,
        "base1": hex(base1),
        "size1": size1,
    }


def get_sdmp_block(jpeg: Path, marker_wanted: int, tag_wanted: int, *, prefer_dims: bool = False) -> bytes:
    data = jpeg.read_bytes()
    found: list[bytes] = []
    for _marker_start, marker, _payload_start, payload in iter_jpeg_segments(data):
        if marker != marker_wanted or not payload.startswith(b"SDMP"):
            continue
        entries = parse_sdmp_ifd(payload)
        by_tag = {e.tag: e for e in entries}
        e = by_tag.get(tag_wanted)
        if not e or e.data_offset_from_payload_start is None or e.byte_count is None:
            continue
        if prefer_dims:
            if by_tag.get(2) is None or by_tag.get(3) is None:
                continue
            if by_tag[2].value_or_offset != WIDTH or by_tag[3].value_or_offset != HEIGHT:
                continue
        found.append(payload[e.data_offset_from_payload_start : e.data_offset_from_payload_start + e.byte_count])
    if not found:
        raise RuntimeError(f"missing marker={marker_wanted:#x} tag={tag_wanted} in {jpeg}")
    return found[-1]


def extract_json(jpeg: Path, tag: int = 6) -> dict[str, object]:
    block = get_sdmp_block(jpeg, 0xE3, tag)
    with zipfile.ZipFile(io.BytesIO(block)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".json")]
        if not names:
            raise RuntimeError(f"zip tag {tag} contains no json: {zf.namelist()}")
        return json.loads(zf.read(names[0]).decode("utf-8-sig"))


def radiometric_q_params(jpeg: Path) -> dict[str, int | float]:
    data = extract_json(jpeg, 6)
    r = data["Radiometric"]
    ta = r["TA"]
    env = ta["EnvironmentalParameters"]
    win = ta["IRWindow"]
    expert = ta["Rules"][0]["Rule_ExpertParameters"]
    return {
        "atmospheric_q13": int(env["AtmosphericTemperature"]["d3"]),
        "humidity_q13": int(round(float(env["Humidity"]) * 8192.0)),
        "window_trans_q13": int(win["OpticsTransmittance"]["d3"]),
        "window_temp_milli_c": int(round(int(win["OpticsTemperature"]["d3"]) / 8192.0 * 1000.0)),
        "emissivity_q13": int(expert["Emissivity"]["d3"]),
        "reflected_q13": int(expert["ReflectedTemperature"]["d3"]),
        "distance_q13": int(expert["Distance"]["d3"]),
        "atmospheric_c": int(env["AtmosphericTemperature"]["d3"]) / 8192.0,
        "reflected_c": int(expert["ReflectedTemperature"]["d3"]) / 8192.0,
        "distance_m": int(expert["Distance"]["d3"]) / 8192.0,
    }


def raw_path_for(jpeg: Path) -> Path:
    candidates = [
        Path("data/mini2_multi_image_formula/raw") / f"{jpeg.stem}_lpld_raw_u16_256x192.bin",
        Path(r"C:\Users\Jio\Downloads\auto_titration_20260513-170048\data\mini2_multi_image_formula\raw")
        / f"{jpeg.stem}_lpld_raw_u16_256x192.bin",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"raw u16 not found for {jpeg}")


def load_raw_u16(jpeg: Path) -> list[int]:
    raw_path = raw_path_for(jpeg)
    data = raw_path.read_bytes()
    if len(data) < PIXELS * 2:
        raise RuntimeError(f"bad raw size {len(data)} in {raw_path}")
    return list(struct.unpack("<" + "H" * PIXELS, data[: PIXELS * 2]))


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
            xs = nums[-WIDTH:]
            if xs and max(xs) <= 150:
                vals.extend(xs)
    if len(vals) != PIXELS:
        raise RuntimeError(f"{path} yielded {len(vals)} values, expected {PIXELS}")
    return vals


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
        "worst_pairs": [[i, i // WIDTH, i % WIDTH, pred[i], truth[i], pred[i] - truth[i]] for i in worst],
    }


def type1_payload(key: int, value: int) -> bytes:
    return struct.pack("<II", int(key), int(value) & 0xFFFFFFFF)


def buf(data: bytes):
    return ctypes.create_string_buffer(data, len(data))


def convert_one(args, jpeg: Path) -> dict[str, object]:
    add_dll_dir(args.dll_dir)
    dll = ctypes.WinDLL(str(args.dll_dir / "MTlib_OL.dll"))
    MT_GetMemSize = dll.MT_GetMemSize_INT
    MT_GetMemSize.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    MT_GetMemSize.restype = ctypes.c_int
    MT_Create = dll.MT_Create_INT
    MT_Create.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    MT_Create.restype = ctypes.c_int
    MT_SetConfig = dll.MT_SetConfig_INT
    MT_SetConfig.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    MT_SetConfig.restype = ctypes.c_int
    MT_Process = dll.MT_Process_INT
    MT_Process.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    MT_Process.restype = ctypes.c_int

    tag519 = get_sdmp_block(jpeg, 0xE2, 519)
    tag1 = get_sdmp_block(jpeg, 0xE3, 1, prefer_dims=True)
    tag1_u16 = struct.unpack("<512H", tag1)
    params_q = radiometric_q_params(jpeg)
    raw = load_raw_u16(jpeg)

    params = ctypes.create_string_buffer(0x20)
    # Analyzer trace proves the first two fields are width/height.  The
    # remaining fields are allocator/context flags; 1/1 works with MT_Create_INT.
    struct.pack_into("<IIII", params, 0, WIDTH, HEIGHT, 1, 1)
    backing, desc, desc_info = make_desc()
    memsize_ret = MT_GetMemSize(ctypes.byref(params), ctypes.byref(desc))
    backing, desc, desc_info = make_desc()
    handle = ctypes.c_void_p()
    create_ret = MT_Create(ctypes.byref(params), ctypes.byref(desc), ctypes.byref(handle))

    report: dict[str, object] = {
        "jpeg": str(jpeg),
        "raw_path": str(raw_path_for(jpeg)),
        "raw_stats": {"min": min(raw), "max": max(raw), "mean": sum(raw) / len(raw)},
        "mt_create": {
            "memsize_ret": memsize_ret,
            "create_ret": create_ret,
            "handle": hex(handle.value) if handle.value else None,
            "desc_info": desc_info,
        },
        "radiometric_params": params_q,
        "tag1_u16_256_320": list(tag1_u16[256:320]),
        "tag1_internal_word_284": int(tag1_u16[284]),
        "setconfig": [],
    }
    if create_ret != 0 or not handle.value:
        return report

    config_items = [
        (6, tag519, "APP2 tag519 calibration"),
        (1, type1_payload(13, 0), "key13=0"),
        (1, type1_payload(45, 1), "key45=1"),
        (1, type1_payload(29, 0), "key29=0"),
        (1, type1_payload(55, 0), "key55=0"),
        (1, type1_payload(14, 0), "key14=0"),
        (1, type1_payload(5, int(params_q["atmospheric_q13"])), "key5 atmospheric q13"),
        (1, type1_payload(6, int(params_q["humidity_q13"])), "key6 humidity*8192"),
        (1, type1_payload(20, int(params_q["window_trans_q13"])), "key20 window trans q13"),
        (1, type1_payload(21, int(params_q["window_temp_milli_c"])), "key21 window temp milli C"),
        (189, struct.pack("<IIII", int(tag1_u16[284]), 0, 0, 0), "type189 tag1_u16[284]"),
        (1, type1_payload(152, 1), "key152=1"),
        (12, tag1, "APP3 tag1 addline"),
    ]
    keepalive = []
    for typ, data, name in config_items:
        b = buf(data)
        keepalive.append(b)
        ret = MT_SetConfig(handle, typ, ctypes.cast(b, ctypes.c_void_p), len(data))
        report["setconfig"].append({
            "type": typ,
            "name": name,
            "len": len(data),
            "ret": ret,
            "first_u32": list(struct.unpack("<" + "I" * min(4, len(data) // 4), data[: min(16, len(data))]))
            if len(data) >= 4 else [],
        })

    n = PIXELS if args.limit <= 0 else min(args.limit, PIXELS)
    out_ints: list[int] = []
    rets: list[int] = []
    batch = max(1, int(args.batch))
    for start in range(0, n, batch):
        count = min(batch, n - start)
        pts = ctypes.create_string_buffer(count * POINT_SIZE)
        for j in range(count):
            off = j * POINT_SIZE
            gray = raw[start + j]
            struct.pack_into("<i", pts, off + 0x04, int(gray))
            # Official Analyzer trace before MT_Process_INT:
            #   +0x14 emissivity q13, +0x18 reflected q13, +0x1c distance q13.
            struct.pack_into("<I", pts, off + 0x14, int(params_q["emissivity_q13"]))
            struct.pack_into("<I", pts, off + 0x18, int(params_q["reflected_q13"]))
            struct.pack_into("<I", pts, off + 0x1C, int(params_q["distance_q13"]))
        ret = MT_Process(handle, 0, ctypes.cast(pts, ctypes.c_void_p), count)
        rets.append(int(ret))
        for j in range(count):
            off = j * POINT_SIZE
            out_ints.append(struct.unpack_from("<i", pts.raw, off + 0x10)[0])
    temps = [v / 64.0 for v in out_ints]
    report["conversion"] = {
        "count": n,
        "batch": batch,
        "process_rets_unique": sorted(set(rets)),
        "out_int_scale": "temperature_c = point_i32_at_0x10 / 64",
        "out_int_minmax": [min(out_ints), max(out_ints)] if out_ints else None,
        "temp_c_minmax": [min(temps), max(temps)] if temps else None,
        "temp_c_mean": sum(temps) / len(temps) if temps else None,
        "first32": [
            {"gray": int(raw[i]), "out_i32": int(out_ints[i]), "temp_c": temps[i]}
            for i in range(min(32, len(temps)))
        ],
    }
    csv_path = args.csv or jpeg.with_name(f"{jpeg.stem}_이미지.csv")
    if csv_path.exists():
        truth = csv_matrix(csv_path)[:n]
        report["validation_vs_csv"] = validate(temps, truth)
    if args.save_matrix:
        args.save_matrix.parent.mkdir(parents=True, exist_ok=True)
        with args.save_matrix.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            for y in range(0, len(temps), WIDTH):
                w.writerow([f"{v:.6f}" for v in temps[y : y + WIDTH]])
        report["saved_matrix"] = str(args.save_matrix)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, required=True)
    ap.add_argument("--csv", type=Path)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--save-matrix", type=Path)
    ap.add_argument("--out", type=Path, default=Path("data/mini2_mtlib_official_matrix"))
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    report = convert_one(args, args.jpeg)
    out_path = args.out / f"{args.jpeg.stem}_mtlib_official_matrix.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        "jpeg": report.get("jpeg"),
        "mt_create": report.get("mt_create"),
        "radiometric_params": report.get("radiometric_params"),
        "tag1_internal_word_284": report.get("tag1_internal_word_284"),
        "setconfig_rets": [(x["type"], x["ret"], x["name"]) for x in report.get("setconfig", [])],
        "conversion": report.get("conversion"),
        "validation_vs_csv": report.get("validation_vs_csv"),
        "out": str(out_path),
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2)[:20000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
