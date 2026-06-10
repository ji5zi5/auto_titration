#!/usr/bin/env python3
"""Probe HIKMICRO Analyzer MTlib_OL raw gray -> temperature path.

This is NOT a CSV fitting script. It feeds the same per-image Mini2 radiometric
blocks into the Analyzer DLL API and asks MTlib_OL to compute temperatures.
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

DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
WIDTH = 256
HEIGHT = 192
POINT_SIZE = 0x24

# Import parser helpers from the sibling extraction script.
THIS = Path(__file__).resolve()
TOOLS = THIS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
from mini2_extract_rjpeg_raw_win import iter_jpeg_segments, parse_sdmp_ifd  # noqa: E402


def add_dll_dir(p: Path) -> None:
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(p))
    ctypes.windll.kernel32.SetDllDirectoryW(str(p))


def c_addr(buf) -> int:
    return ctypes.addressof(buf)


def align128(x: int) -> int:
    return (x + 0x7F) & ~0x7F


def read_u32(addr: int, off: int) -> int:
    return ctypes.c_uint32.from_address(addr + off).value


def read_i32(addr: int, off: int) -> int:
    return ctypes.c_int32.from_address(addr + off).value


def read_u16(addr: int, off: int) -> int:
    return ctypes.c_uint16.from_address(addr + off).value


def read_u8(addr: int, off: int) -> int:
    return ctypes.c_uint8.from_address(addr + off).value


def read_f32(addr: int, off: int) -> float:
    return ctypes.c_float.from_address(addr + off).value


def read_ptr(addr: int, off: int) -> int:
    return ctypes.c_void_p.from_address(addr + off).value or 0


def bytes_at(addr: int, n: int) -> bytes:
    return ctypes.string_at(addr, n)


def csv_matrix(path: Path) -> list[list[float]]:
    # HIKMICRO Analyzer CSV from Korean Windows is commonly CP949, and it
    # includes a text header plus row/column indices. Keep only 256-wide
    # temperature rows; do not use this for fitting, only validation.
    last_err = None
    text = None
    for enc in ['utf-8-sig', 'cp949', 'euc-kr', 'latin1']:
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError as exc:
            last_err = exc
    if text is None:
        raise last_err or UnicodeDecodeError('unknown', b'', 0, 0, 'decode failed')
    rows: list[list[float]] = []
    for row in csv.reader(text.splitlines()):
        nums: list[float] = []
        for cell in row:
            cell = cell.strip()
            if not cell:
                continue
            try:
                nums.append(float(cell))
            except ValueError:
                pass
        if len(nums) >= WIDTH:
            vals = nums[-WIDTH:]
            # Skip the X/Y column header row 0..255.
            if vals and max(vals) > 150:
                continue
            rows.append(vals)
    return rows


def matrix_flat_rows(mat: list[list[float]]) -> list[float]:
    return [v for row in mat for v in row]


def get_sdmp_block(jpeg: Path, marker_wanted: int, tag_wanted: int, *, prefer_dims: bool = False) -> bytes:
    data = jpeg.read_bytes()
    found: list[bytes] = []
    for _ms, marker, _ps, payload in iter_jpeg_segments(data):
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
        found.append(payload[e.data_offset_from_payload_start:e.data_offset_from_payload_start + e.byte_count])
    if not found:
        raise RuntimeError(f"missing SDMP tag {tag_wanted} marker {marker_wanted:#x} in {jpeg}")
    return found[-1]


def extract_blocks(jpeg: Path) -> dict[str, bytes]:
    # APP2 tag519 = per-device calibration block, 0x3800 bytes.
    tag519 = get_sdmp_block(jpeg, 0xE2, 519)
    # APP3 tag1 = two 256-wide uint16 metadata/addline rows, 1024 bytes.
    tag1 = get_sdmp_block(jpeg, 0xE3, 1, prefer_dims=True)
    if len(tag519) != 0x3800:
        raise RuntimeError(f"unexpected tag519 size {len(tag519)}")
    if len(tag1) != WIDTH * 2 * 2:
        raise RuntimeError(f"unexpected tag1/addline size {len(tag1)}")
    return {"tag519": tag519, "tag1": tag1}


def extract_zipped_json(jpeg: Path, tag_wanted: int) -> dict[str, object]:
    """Extract one of HIKMICRO's zipped JSON SDMP APP3 payloads.

    The Mini2 JPEGs store Radiometric.json as APP3/SDMP tag 6. This lets this
    probe apply the same embedded environmental/expert parameters without
    relying on a separately exported CSV answer.
    """
    block = get_sdmp_block(jpeg, 0xE3, tag_wanted)
    with zipfile.ZipFile(io.BytesIO(block)) as zf:
        json_names = [name for name in zf.namelist() if name.lower().endswith(".json")]
        if not json_names:
            raise RuntimeError(f"APP3 tag {tag_wanted} zip has no JSON: {zf.namelist()}")
        return json.loads(zf.read(json_names[0]).decode("utf-8-sig"))


def d3_to_float(value: int) -> float:
    return float(value) / 8192.0


def radiometric_params_from_jpeg(jpeg: Path) -> dict[str, float]:
    data = extract_zipped_json(jpeg, 6)
    r = data["Radiometric"]
    ta = r["TA"]
    env = ta["EnvironmentalParameters"]
    win = ta["IRWindow"]
    expert = ta["Rules"][0]["Rule_ExpertParameters"]
    return {
        "atmospheric_c": d3_to_float(env["AtmosphericTemperature"]["d3"]),
        "humidity_percent": float(env["Humidity"]),
        "optics_transmittance": d3_to_float(win["OpticsTransmittance"]["d3"]),
        "optics_temperature_c": d3_to_float(win["OpticsTemperature"]["d3"]),
        "reflected_c": d3_to_float(expert["ReflectedTemperature"]["d3"]),
        "distance_m": d3_to_float(expert["Distance"]["d3"]),
        "emissivity": d3_to_float(expert["Emissivity"]["d3"]),
    }


def tag1_internal_reflected_c(tag1: bytes) -> float:
    """Mini2 APP3 tag1 internal reflected/sensor temperature used by MTlib.

    Reverse + validation evidence: tag1 starts with two 256-wide uint16 rows.
    For Mini2 captures, row0 words 0, 1, 20, and 25 are internal camera
    temperatures scaled by 50. HIKMICRO Analyzer's MTlib path matches exported
    matrices when the per-point reflected field is their average.
    """
    vals = struct.unpack("<256H", tag1[: WIDTH * 2])
    return (vals[0] + vals[1] + vals[20] + vals[25]) / (4.0 * 50.0)


def encode_type1_value(key: int, value: float) -> int:
    """Encode human units into MT_SetConfig(type=1) integer values.

    This mapping is from MTlib_OL's key/value setter:
    - keys writing temperatures/distances through `value*0.001` take milli-units
    - humidity-like key 6 writes `value * 1e-5`, so percent 60 -> 60000 -> 0.6
    - emissivity key 19 writes `value*0.001`, so 0.97 -> 970
    """
    if key == 6:
        # key 6 stores value * 0.001 * 0.01. HIK JSON humidity is percent.
        # 60 (%) -> 60000 -> 0.6 fraction in the handle.
        return int(round(value * 1000.0))
    if key == 7:
        # key 7 stores value * 0.001 * 0.001.
        return int(round(value * 1_000_000.0))
    if key == 19:
        return int(round(value * 1000.0))
    return int(round(value * 1000.0))


def parse_key_value(text: str, *, raw: bool = False) -> tuple[int, int, float | int]:
    if "=" not in text:
        raise argparse.ArgumentTypeError("expected KEY=VALUE")
    k_s, v_s = text.split("=", 1)
    try:
        key = int(k_s, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"bad key in {text!r}") from exc
    if raw:
        try:
            raw_value = int(v_s, 0)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"bad raw int value in {text!r}") from exc
        return key, raw_value, raw_value
    try:
        value = float(v_s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"bad float value in {text!r}") from exc
    return key, encode_type1_value(key, value), value


def type1_payload(key: int, encoded_value: int) -> bytes:
    return struct.pack("<II", int(key), int(encoded_value) & 0xFFFFFFFF)


def radiometric_type1_pairs(params: dict[str, float], profile: str) -> list[tuple[int, float, str]]:
    """Return non-fitted MT_SetConfig(type=1) pairs from embedded JPEG metadata.

    Profiles are deliberately explicit so experiments can show which DLL fields
    matter. They do not use the Analyzer CSV answer matrix.
    """
    if profile == "none":
        return []
    common = [
        (5, params["atmospheric_c"], "key5 atmospheric_c -> handle+0xd0"),
        (6, params["humidity_percent"], "key6 humidity_percent -> handle+0xd4 fraction"),
        (19, params["emissivity"], "key19 emissivity -> handle+0x60"),
        (20, params["distance_m"], "key20 distance_m -> handle+0x68"),
    ]
    if profile == "basic":
        return common
    if profile == "with_window":
        return common + [
            (7, params["optics_transmittance"], "key7 optics_transmittance candidate -> handle+0xd8"),
            (8, params["optics_temperature_c"], "key8 optics_temperature_c candidate -> handle+0xdc"),
        ]
    if profile == "with_expert":
        return common + [
            (21, params["reflected_c"], "key21 reflected_c candidate -> handle+0x6c"),
            (34, params["optics_temperature_c"], "key34 optics_temperature_c candidate -> handle+0x64"),
            (37, params["reflected_c"], "key37 reflected_c candidate -> handle+0x70"),
        ]
    if profile == "all_known":
        return common + [
            (7, params["optics_transmittance"], "key7 optics_transmittance candidate -> handle+0xd8"),
            (8, params["optics_temperature_c"], "key8 optics_temperature_c candidate -> handle+0xdc"),
            (21, params["reflected_c"], "key21 reflected_c candidate -> handle+0x6c"),
            (34, params["optics_temperature_c"], "key34 optics_temperature_c candidate -> handle+0x64"),
            (37, params["reflected_c"], "key37 reflected_c candidate -> handle+0x70"),
        ]
    raise ValueError(profile)


def raw_path_for(jpeg: Path) -> Path:
    candidates = [
        Path('data/mini2_multi_image_formula/raw') / f"{jpeg.stem}_lpld_raw_u16_256x192.bin",
        Path('/mnt/c/Users/Jio/Downloads/auto_titration_20260513-170048/data/mini2_multi_image_formula/raw') / f"{jpeg.stem}_lpld_raw_u16_256x192.bin",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise RuntimeError(f"raw u16 file not found for {jpeg}")


def make_desc(total_size: int = 0x600000):
    # One contiguous backing buffer, but two 128-byte-aligned allocator regions.
    backing = ctypes.create_string_buffer(total_size + 0x400)
    base0 = align128(c_addr(backing))
    # Region 1 holds MT handle + fixed calibration area. Region 2 is MT work area.
    base1 = align128(base0 + 0x500 + 0x3D00)
    size0 = base1 - base0
    size1 = (c_addr(backing) + len(backing)) - base1
    size0 &= ~0x7F
    size1 &= ~0x7F
    desc = ctypes.create_string_buffer(0x40)
    struct.pack_into('<QII', desc, 0x00, base0, size0, 0x80)
    struct.pack_into('<I', desc, 0x14, 1)
    struct.pack_into('<QII', desc, 0x18, base1, size1, 0x80)
    struct.pack_into('<I', desc, 0x2C, 0)
    return backing, desc, {"base0": hex(base0), "size0": size0, "base1": hex(base1), "size1": size1}


def buf_from_bytes(data: bytes):
    return ctypes.create_string_buffer(data, len(data))


def inspect_handle(handle: int) -> dict[str, object]:
    rep: dict[str, object] = {"handle": hex(handle) if handle else None}
    if not handle:
        return rep
    offsets_i32 = [0x0, 0x4, 0x8, 0xc, 0x10, 0x14, 0x18, 0x30, 0x34, 0x38, 0x3c, 0x40, 0x44, 0x4c, 0x50, 0x5c, 0xcc, 0xf8, 0xfc, 0x100, 0x104, 0x128, 0x12c, 0x370, 0x374, 0x380, 0x43c, 0x440, 0x444, 0x4cc]
    rep["i32"] = {hex(o): read_i32(handle, o) for o in offsets_i32}
    offsets_f32 = [0x60,0x64,0x68,0x6c,0x70,0x74,0x78,0x7c,0x80,0x84,0x88,0x8c,0x90,0x94,0xd0,0xd4,0xd8,0xdc,0xe0,0xe4,0xe8,0xec,0xf0,0xf4,0x108,0x10c,0x110,0x114,0x118,0x134,0x138,0x13c,0x4d4]
    rep["f32"] = {hex(o): read_f32(handle, o) for o in offsets_f32}
    offsets_u8 = [0,1,2,3,4,0xf8,0xf9,0xfa,0xfb,0x124,0x159,0x1a2,0x1a3,0x1a4,0x1a5,0x1a6,0x4d0,0x4d1,0x4d2,0x498]
    rep["u8"] = {hex(o): read_u8(handle, o) for o in offsets_u8}
    ptrs = [0x140,0x148,0x150,0x180,0x188,0x1a8,0x1b0,0x1b8,0x1c0,0x1c8,0x1d0,0x368,0x378,0x418,0x420,0x428,0x430,0x488,0x490]
    rep["ptrs"] = {hex(o): hex(read_ptr(handle, o)) if read_ptr(handle, o) else None for o in ptrs}
    calib = read_ptr(handle, 0x140)
    if calib:
        prefix = bytes_at(calib, 96)
        rep["calib_prefix_hex"] = prefix.hex(' ')
        rep["calib_ascii_16_64"] = ''.join(chr(b) if 32 <= b < 127 else '.' for b in bytes_at(calib + 0x10, 64))
        rep["calib_u32_0_32"] = [struct.unpack_from('<I', bytes_at(calib, 128), i)[0] for i in range(0, 128, 4)]
        # Known candidate region values around tag519 0x36fc..0x3760 after parse/copy.
        rep["calib_f32_key"] = {hex(o): read_f32(calib, o) for o in [0x21b0,0x21b4,0x21b8,0x21bc,0x21c4,0x21c8,0x27ec,0x27f0,0x36d8,0x36dc,0x36fc,0x3700,0x3704,0x3708,0x370c,0x3710,0x3714,0x374c,0x3754,0x3758,0x375c,0x3760] if o < 0x3800}
        rep["calib_u8_key"] = {hex(o): read_u8(calib, o) for o in [0x10,0x11,0x12,0x13,0x14,0x15,0x16,0x17,0x374c,0x374d] if o < 0x3800}
    return rep


def make_points(raw_u16: list[int], count: int, mode: str, emissivity: float = 0.970, reflected_c: float = 25.0, distance_m: float = 1.0) -> ctypes.Array:
    pts = ctypes.create_string_buffer(count * POINT_SIZE)
    if mode == 'samples':
        indices = [0, WIDTH//2, WIDTH*HEIGHT//2 + WIDTH//2, WIDTH*HEIGHT - 1]
        indices = indices[:count]
    elif mode == 'all':
        indices = list(range(count))
    else:
        raise ValueError(mode)
    for i, idx in enumerate(indices):
        off = i * POINT_SIZE
        gray = raw_u16[idx]
        # Fields observed in MTlib_OL:
        # +4 raw point gray; +0x14 emissivity, +0x18 reflected/ambient C, +0x1c distance.
        struct.pack_into('<i', pts, off + 0x04, int(gray))
        struct.pack_into('<f', pts, off + 0x14, float(emissivity))
        struct.pack_into('<f', pts, off + 0x18, float(reflected_c))
        struct.pack_into('<f', pts, off + 0x1C, float(distance_m))
    return pts


def adjusted_gray(gray: int, delta: int = 0, scale: float = 1.0, offset: float = 0.0) -> int:
    """Apply diagnostic gray adjustment before feeding MTlib.

    This is for reverse-engineering evidence only: it tests whether Analyzer's
    exported matrix is using the decompressed raw gray directly or a simple
    corrected gray domain. It is not a CSV lookup and should not be used as a
    final formula unless a metadata/DLL source for the adjustment is proven.
    """
    value = int(round((int(gray) + int(delta)) * float(scale) + float(offset)))
    return max(0, min(65535, value))


def parse_outputs(pts, count: int, indices: list[int] | None = None) -> list[dict[str, object]]:
    out = []
    for i in range(count):
        off = i * POINT_SIZE
        out.append({
            "i": i if indices is None else indices[i],
            "ret_code_at_0": struct.unpack_from('<i', pts.raw, off + 0x00)[0],
            "gray_at_4": struct.unpack_from('<i', pts.raw, off + 0x04)[0],
            "temp_float_at_10": struct.unpack_from('<f', pts.raw, off + 0x10)[0],
            "emissivity_at_14": struct.unpack_from('<f', pts.raw, off + 0x14)[0],
            "reflected_at_18": struct.unpack_from('<f', pts.raw, off + 0x18)[0],
            "distance_at_1c": struct.unpack_from('<f', pts.raw, off + 0x1C)[0],
            "scaled_int_at_20": struct.unpack_from('<i', pts.raw, off + 0x20)[0],
        })
    return out


def run_one(
    jpeg: Path,
    dll_dir: Path,
    process_all: bool = False,
    all_limit: int = 0,
    emissivity: float = 0.970,
    reflected_c: float = 25.0,
    reflected_source: str = "cli",
    distance_m: float = 1.0,
    radiometric_profile: str = "none",
    set_keys: list[tuple[int, int, float | int]] | None = None,
    set_keys_raw: list[tuple[int, int, float | int]] | None = None,
    all_batch: int = 4,
    api_variant: str = "standard",
    process_export: str = "MT_Process",
    save_temps_csv: Path | None = None,
    gray_delta: int = 0,
    gray_scale: float = 1.0,
    gray_offset: float = 0.0,
) -> dict[str, object]:
    add_dll_dir(dll_dir)
    dll = ctypes.WinDLL(str(dll_dir / 'MTlib_OL.dll'))
    suffix = "" if api_variant == "standard" else f"_{api_variant}"
    MT_GetMemSize = getattr(dll, f"MT_GetMemSize{suffix}")
    MT_GetMemSize.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    MT_GetMemSize.restype = ctypes.c_int
    MT_Create = getattr(dll, f"MT_Create{suffix}")
    MT_Create.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    MT_Create.restype = ctypes.c_int
    MT_SetConfig = getattr(dll, f"MT_SetConfig{suffix}")
    MT_SetConfig.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    MT_SetConfig.restype = ctypes.c_int
    MT_Process = getattr(dll, process_export)
    MT_Process.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    MT_Process.restype = ctypes.c_int

    blocks = extract_blocks(jpeg)
    tag1_reflected_c = tag1_internal_reflected_c(blocks["tag1"])
    raw_path = raw_path_for(jpeg)
    raw = raw_path.read_bytes()
    if len(raw) != WIDTH * HEIGHT * 2:
        raise RuntimeError(f"bad raw size {len(raw)}")
    raw_u16 = list(struct.unpack('<' + 'H' * (WIDTH * HEIGHT), raw))
    raw_frame = raw + blocks['tag1']
    if reflected_source == "tag1_internal_avg":
        reflected_c = tag1_reflected_c

    params = ctypes.create_string_buffer(0x20)
    struct.pack_into('<IIII', params, 0, WIDTH, HEIGHT, 1, 1)

    backing, desc, desc_info = make_desc()
    memsize_ret = MT_GetMemSize(ctypes.byref(params), ctypes.byref(desc))
    desc_after_memsize = bytes(desc).hex(' ')

    # Rebuild descriptor because MT_GetMemSize mutates size fields.
    backing, desc, desc_info = make_desc()
    handle = ctypes.c_void_p()
    create_ret = MT_Create(ctypes.byref(params), ctypes.byref(desc), ctypes.byref(handle))
    h = int(handle.value or 0)
    radiometric_params: dict[str, float] | None = None
    try:
        radiometric_params = radiometric_params_from_jpeg(jpeg)
    except Exception:
        radiometric_params = None

    report: dict[str, object] = {
        "jpeg": str(jpeg),
        "raw_path": str(raw_path),
        "raw_stats": {"min": min(raw_u16), "max": max(raw_u16), "mean": sum(raw_u16)/len(raw_u16)},
        "radiometric_params_from_jpeg": radiometric_params,
        "radiometric_type1_profile": radiometric_profile,
        "tag1_internal_reflected_c": tag1_reflected_c,
        "tag1_internal_reflected_formula": "(tag1_u16[0] + tag1_u16[1] + tag1_u16[20] + tag1_u16[25]) / (4*50)",
        "tag519_len": len(blocks['tag519']),
        "tag519_prefix_hex": blocks['tag519'][:64].hex(' '),
        "tag1_len": len(blocks['tag1']),
        "tag1_u16_first_64": list(struct.unpack('<64H', blocks['tag1'][:128])),
        "desc_info": desc_info,
        "memsize_ret": memsize_ret,
        "api_variant": api_variant,
        "process_export": process_export,
        "desc_after_memsize_hex": desc_after_memsize,
        "create_ret": create_ret,
        "handle_after_create": inspect_handle(h),
        "expert_params": {"emissivity": emissivity, "reflected_c": reflected_c, "reflected_source": reflected_source, "distance_m": distance_m},
        "gray_adjustment": {"delta": gray_delta, "scale": gray_scale, "offset": gray_offset},
        "setconfig": [],
        "process": [],
    }
    if create_ret != 0 or not h:
        return report

    # Try known config path: tag519 calibration, raw+addline frame.
    # MT_SetConfig(type=1) accepts an 8-byte key/value pair. Reverse mapping
    # shows key 15 writes handle+0x30, the calibration-parameter type that
    # MT_Process checks against tag519[+8]. For Mini2 tag519[+8] is 83.
    calib_param_type = struct.unpack_from('<I', blocks['tag519'], 0x08)[0]
    cfg_calib_type = struct.pack('<II', 15, calib_param_type)
    config_items: list[tuple[int, bytes, str]] = [
        (6, blocks['tag519'], 'APP2 tag519 calibration block'),
        (1, cfg_calib_type, f'key/value: key15 calibration-param-type={calib_param_type}'),
    ]
    if radiometric_params:
        for key, value, label in radiometric_type1_pairs(radiometric_params, radiometric_profile):
            encoded = encode_type1_value(key, value)
            config_items.append((1, type1_payload(key, encoded), f"{label}; value={value} encoded={encoded}"))
    for key, encoded, original in set_keys or []:
        config_items.append((1, type1_payload(key, encoded), f"manual key{key} value={original} encoded={encoded}"))
    for key, encoded, original in set_keys_raw or []:
        config_items.append((1, type1_payload(key, encoded), f"manual raw key{key} raw_value={original}"))
    config_items.append((7, raw_frame, 'raw 256x192 u16 + APP3 tag1 two addline rows'))
    for typ, data, name in config_items:
        buf = buf_from_bytes(data)
        ret = MT_SetConfig(handle, typ, ctypes.cast(buf, ctypes.c_void_p), len(data))
        report["setconfig"].append({"type": typ, "name": name, "len": len(data), "ret": ret, "handle": inspect_handle(h)})

    # Sample process with representative grays.
    sample_indices = [0, WIDTH//2, WIDTH*HEIGHT//2 + WIDTH//2, WIDTH*HEIGHT - 1]
    pts = make_points(raw_u16, len(sample_indices), 'samples', emissivity, reflected_c, distance_m)
    proc_types = [] if process_all else [0, 1, 2, 3]
    for proc_type in proc_types:
        # fresh points each type, because MT_Process overwrites them.
        pts = make_points(raw_u16, len(sample_indices), 'samples', emissivity, reflected_c, distance_m)
        ret = MT_Process(handle, proc_type, ctypes.cast(pts, ctypes.c_void_p), len(sample_indices))
        report["process"].append({"process_type": proc_type, "ret": ret, "points": parse_outputs(pts, len(sample_indices), sample_indices)})

    if process_all:
        # MT_Process keeps a small per-call stack temp array, so do all-pixel
        # validation in conservative batches rather than one 49152-point call.
        temps: list[float] = []
        codes: list[int] = []
        batch_rets: list[int] = []
        batch = max(1, int(all_batch))
        total_n = min(len(raw_u16), all_limit) if all_limit else len(raw_u16)
        for start in range(0, total_n, batch):
            n = min(batch, total_n - start)
            pts_b = ctypes.create_string_buffer(n * POINT_SIZE)
            for j in range(n):
                off = j * POINT_SIZE
                gray = adjusted_gray(raw_u16[start + j], gray_delta, gray_scale, gray_offset)
                struct.pack_into('<i', pts_b, off + 0x04, gray)
                struct.pack_into('<f', pts_b, off + 0x14, float(emissivity))
                struct.pack_into('<f', pts_b, off + 0x18, float(reflected_c))
                struct.pack_into('<f', pts_b, off + 0x1C, float(distance_m))
            ret = MT_Process(handle, 0, ctypes.cast(pts_b, ctypes.c_void_p), n)
            batch_rets.append(ret)
            for j in range(n):
                temps.append(struct.unpack_from('<f', pts_b.raw, j * POINT_SIZE + 0x10)[0])
                codes.append(struct.unpack_from('<i', pts_b.raw, j * POINT_SIZE + 0x00)[0])
        report["process_all_type0"] = {
            "batch": batch,
            "limit": all_limit,
            "count": len(temps),
            "batch_rets_unique": sorted(set(batch_rets)),
            "temp_min": min(temps),
            "temp_max": max(temps),
            "temp_mean": sum(temps)/len(temps),
            "codes_unique_first20": sorted(set(codes))[:20],
            "temps_first16": temps[:16],
        }
        if save_temps_csv is not None:
            save_temps_csv.parent.mkdir(parents=True, exist_ok=True)
            with save_temps_csv.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                for y in range(0, len(temps), WIDTH):
                    writer.writerow([f"{v:.6f}" for v in temps[y:y + WIDTH]])
            report["process_all_type0"]["saved_temps_csv"] = str(save_temps_csv)
        csv_path = jpeg.with_name(f"{jpeg.stem}_이미지.csv")
        if csv_path.exists():
            ref = matrix_flat_rows(csv_matrix(csv_path))
            if len(ref) >= len(temps):
                diffs = [temps[i] - ref[i] for i in range(len(temps)) if math.isfinite(temps[i])]
                rounded_diffs = [round(temps[i], 1) - ref[i] for i in range(len(temps)) if math.isfinite(temps[i])]
                worst_idx = sorted(
                    (i for i in range(len(temps)) if math.isfinite(temps[i])),
                    key=lambda i: abs(temps[i] - ref[i]),
                    reverse=True,
                )[:16]
                report["validation_vs_csv"] = {
                    "csv": str(csv_path),
                    "count": len(diffs),
                    "mae": sum(abs(d) for d in diffs)/len(diffs),
                    "max_abs": max(abs(d) for d in diffs),
                    "bias": sum(diffs)/len(diffs),
                    "rounded_0p1_mae": sum(abs(d) for d in rounded_diffs)/len(rounded_diffs),
                    "rounded_0p1_max_abs": max(abs(d) for d in rounded_diffs),
                    "rounded_0p1_match_rate": sum(1 for d in rounded_diffs if abs(d) < 1e-6)/len(rounded_diffs),
                    "count_abs_gt_0p05": sum(1 for d in diffs if abs(d) > 0.05),
                    "count_abs_gt_0p10": sum(1 for d in diffs if abs(d) > 0.10),
                    "sample_pairs": [[temps[i], ref[i], temps[i]-ref[i]] for i in [i for i in [0, WIDTH//2, WIDTH*HEIGHT//2+WIDTH//2, WIDTH*HEIGHT-1] if i < len(temps)]],
                    "worst_pairs": [[i, i // WIDTH, i % WIDTH, temps[i], ref[i], temps[i]-ref[i]] for i in worst_idx],
                }
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dll-dir', type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument('--jpeg', type=Path, default=Path('data/fixtures/mini2/IR_00001.jpeg'))
    ap.add_argument('--all', action='store_true', help='run all-pixel process/CSV validation')
    ap.add_argument('--limit', type=int, default=0, help='limit all-pixel loop for debugging; 0 means no limit')
    ap.add_argument('--batch', type=int, default=4, help='MT_Process points per validation call; keep small because DLL keeps stack scratch')
    ap.add_argument('--api-variant', choices=['standard', 'OL', 'INT'], default='standard', help='which MT_GetMemSize/Create/SetConfig export family to use')
    ap.add_argument('--process-export', choices=['MT_Process', 'MT_Process_OL', 'MT_Process_INT'], default='MT_Process')
    ap.add_argument('--save-temps-csv', type=Path, default=None, help='save computed temperature matrix for diagnostics')
    ap.add_argument('--gray-delta', type=int, default=0, help='diagnostic integer delta applied to every raw gray before MT_Process')
    ap.add_argument('--gray-scale', type=float, default=1.0, help='diagnostic scale applied to adjusted gray before MT_Process')
    ap.add_argument('--gray-offset', type=float, default=0.0, help='diagnostic offset applied after scale before MT_Process')
    ap.add_argument('--emissivity', type=float, default=7946/8192)
    ap.add_argument('--reflected-c', type=float, default=25.0)
    ap.add_argument(
        '--reflected-source',
        choices=['cli', 'tag1_internal_avg'],
        default='cli',
        help='source for per-point reflected temperature; tag1_internal_avg is non-CSV Mini2 metadata',
    )
    ap.add_argument('--distance-m', type=float, default=1.0)
    ap.add_argument(
        '--radiometric-profile',
        choices=['none', 'basic', 'with_window', 'with_expert', 'all_known'],
        default='none',
        help='apply MT_SetConfig(type=1) key/value pairs from embedded Radiometric.json before raw+tag1',
    )
    ap.add_argument(
        '--set-key',
        action='append',
        default=[],
        metavar='KEY=VALUE',
        help='extra MT_SetConfig(type=1) key in human units, encoded per known DLL scale',
    )
    ap.add_argument(
        '--set-key-raw',
        action='append',
        default=[],
        metavar='KEY=INT',
        help='extra MT_SetConfig(type=1) key with raw integer value',
    )
    ap.add_argument('--out', type=Path, default=Path('data/mini2_mtlib_api_probe'))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    set_keys = [parse_key_value(item, raw=False) for item in args.set_key]
    set_keys_raw = [parse_key_value(item, raw=True) for item in args.set_key_raw]
    rep = run_one(
        args.jpeg,
        args.dll_dir,
        process_all=args.all,
        all_limit=args.limit,
        emissivity=args.emissivity,
        reflected_c=args.reflected_c,
        reflected_source=args.reflected_source,
        distance_m=args.distance_m,
        radiometric_profile=args.radiometric_profile,
        set_keys=set_keys,
        set_keys_raw=set_keys_raw,
        all_batch=args.batch,
        api_variant=args.api_variant,
        process_export=args.process_export,
        save_temps_csv=args.save_temps_csv,
        gray_delta=args.gray_delta,
        gray_scale=args.gray_scale,
        gray_offset=args.gray_offset,
    )
    out = args.out / f"{args.jpeg.stem}_mtlib_api_probe.json"
    out.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding='utf-8')
    # Print a compact summary plus path; full JSON goes to disk.
    compact = {
        "jpeg": rep.get('jpeg'),
        "memsize_ret": rep.get('memsize_ret'),
        "create_ret": rep.get('create_ret'),
        "process_export": rep.get('process_export'),
        "api_variant": rep.get('api_variant'),
        "setconfig_rets": [(x['type'], x['ret']) for x in rep.get('setconfig', [])],
        "radiometric_params_from_jpeg": rep.get('radiometric_params_from_jpeg'),
        "radiometric_type1_profile": rep.get('radiometric_type1_profile'),
        "tag1_internal_reflected_c": rep.get('tag1_internal_reflected_c'),
        "expert_params": rep.get('expert_params'),
        "process_rets": [(x['process_type'], x['ret'], [(p['gray_at_4'], p['temp_float_at_10'], p['ret_code_at_0']) for p in x['points']]) for x in rep.get('process', [])],
        "validation_vs_csv": rep.get('validation_vs_csv'),
        "out": str(out),
    }
    print(json.dumps(compact, indent=2, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
