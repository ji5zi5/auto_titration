#!/usr/bin/env python3
"""Extract HIKMICRO Mini2 radiometric JPEG raw matrices with Analyzer's DLL.

This script is intended to be run by Windows Python because it calls
`MicroJPEG_Release_x64.dll` from the installed HIKMICRO Analyzer application.
It does not infer temperatures from JPEG palette colors. It only:

1. Parses the APP3/SDMP radiometric JPEG block.
2. Passes the embedded LPLD compressed block to HIKMICRO's internal
   `UnCompresser`.
3. Writes the decompressed 256x192 little-endian uint16 raw/gray matrix.

The internal RVAs are version-specific and were discovered locally from the
installed HIKMICRO Analyzer build used for this project.
"""

from __future__ import annotations

import argparse
import ctypes
import csv
import json
import os
import struct
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
DLL_NAME = "MicroJPEG_Release_x64.dll"

# Local HIKMICRO Analyzer MicroJPEG_Release_x64.dll RVAs.
RVA_CTOR = 0x66AF0
RVA_DTOR = 0x66D20
RVA_GET_INFO = 0x677F0
RVA_UNCOMPRESS = 0x67340

RAW_WIDTH = 256
RAW_HEIGHT = 192
RAW_BYTES = RAW_WIDTH * RAW_HEIGHT * 2

TYPE_BYTE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}


@dataclass(frozen=True)
class SdmpEntry:
    tag: int
    field_type: int
    count: int
    value_or_offset: int
    byte_count: int | None
    data_offset_from_payload_start: int | None


@dataclass(frozen=True)
class ExtractionCandidate:
    jpeg: str
    app3_marker_file_offset: int
    app3_payload_file_offset: int
    app3_payload_length: int
    lpld_file_offset: int
    lpld_payload_offset: int
    lpld_size_bytes: int
    width_from_sdmp: int | None
    height_from_sdmp: int | None
    pixel_format_from_sdmp: int | None
    first_16_bytes_hex: str


class BareBlock(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.c_void_p),
        ("size", ctypes.c_uint32),
        ("pad", ctypes.c_uint32),
    ]


class MicroJpegUncompresser:
    def __init__(self, dll_dir: Path):
        self.dll_dir = dll_dir
        if not (dll_dir / DLL_NAME).exists():
            raise FileNotFoundError(f"cannot find {dll_dir / DLL_NAME}")

        # Make dependent DLL lookup deterministic on Windows 3.8+.
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(dll_dir))
        ctypes.windll.kernel32.SetDllDirectoryW(str(dll_dir))

        self.dll = ctypes.WinDLL(str(dll_dir / DLL_NAME))
        k32 = ctypes.windll.kernel32
        k32.GetModuleHandleW.restype = ctypes.c_void_p
        base = k32.GetModuleHandleW(DLL_NAME)
        if not base:
            # Some Windows loaders register the full path but not the basename.
            base = k32.GetModuleHandleW(str(dll_dir / DLL_NAME))
        if not base:
            raise RuntimeError(f"GetModuleHandleW failed for {DLL_NAME}")
        self.base = int(base)

        self.ctor = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(self.base + RVA_CTOR)
        self.dtor = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(self.base + RVA_DTOR)
        self.get_info = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
            self.base + RVA_GET_INFO
        )
        self.uncompress = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
            self.base + RVA_UNCOMPRESS
        )

    def extract(self, block: bytes) -> tuple[bytes, dict[str, object]]:
        obj_buf = ctypes.create_string_buffer(0x400)
        obj = ctypes.c_void_p(ctypes.addressof(obj_buf))
        self.ctor(obj)
        try:
            block_buf = ctypes.create_string_buffer(block)
            bare = BareBlock(ctypes.cast(block_buf, ctypes.c_void_p), len(block), 0)
            info_ok = bool(self.get_info(obj, ctypes.byref(bare)))

            raw_info = ctypes.create_string_buffer(0x80)
            uncompress_ok = bool(self.uncompress(obj, ctypes.byref(raw_info), ctypes.byref(bare)))
            words = [int.from_bytes(raw_info.raw[i : i + 4], "little") for i in range(0, 0x28, 4)]
            ptr_size = ctypes.sizeof(ctypes.c_void_p)
            data_ptr = int.from_bytes(raw_info.raw[0x10 : 0x10 + ptr_size], "little")
            data_size = int.from_bytes(raw_info.raw[0x20:0x24], "little")
            width = int.from_bytes(raw_info.raw[0x00:0x04], "little")
            height = int.from_bytes(raw_info.raw[0x04:0x08], "little")
            fmt = int.from_bytes(raw_info.raw[0x08:0x0C], "little")

            evidence = {
                "get_info_ok": info_ok,
                "uncompress_ok": uncompress_ok,
                "raw_info_u32_0x00_to_0x28": words,
                "raw_info_width": width,
                "raw_info_height": height,
                "raw_info_format": fmt,
                "raw_info_data_ptr": hex(data_ptr) if data_ptr else None,
                "raw_info_data_size": data_size,
            }
            if not uncompress_ok:
                raise RuntimeError(f"UnCompresser::unCompress returned false; evidence={evidence}")
            if not data_ptr:
                raise RuntimeError(f"UnCompresser output data pointer is null; evidence={evidence}")
            if data_size < RAW_BYTES:
                raise RuntimeError(f"UnCompresser output too small ({data_size}); evidence={evidence}")
            raw = ctypes.string_at(data_ptr, RAW_BYTES)
            return raw, evidence
        finally:
            try:
                self.dtor(obj)
            except Exception:
                pass


def iter_jpeg_segments(data: bytes):
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("not a JPEG file")
    pos = 2
    while pos < len(data) - 1:
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker_start = pos
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker in {0xD8, 0xD9}:
            continue
        if marker == 0xDA:
            break
        if pos + 2 > len(data):
            break
        length = int.from_bytes(data[pos : pos + 2], "big")
        payload_start = pos + 2
        payload_end = pos + length
        yield marker_start, marker, payload_start, data[payload_start:payload_end]
        pos = payload_end


def parse_sdmp_ifd(payload: bytes) -> list[SdmpEntry]:
    if not payload.startswith(b"SDMP") or len(payload) < 0x12:
        return []
    count = int.from_bytes(payload[0x10:0x12], "little")
    if not (0 < count < 128):
        return []
    entries: list[SdmpEntry] = []
    # HIKMICRO SDMP offsets in these radiometric JPEGs are relative to 0x10.
    # This is why tag0 value 74 points to payload offset 90, whose first bytes
    # are the LPLD header accepted by MicroJPEG's UnCompresser.
    data_base = 0x10
    for i in range(count):
        off = 0x12 + i * 12
        if off + 12 > len(payload):
            break
        tag, field_type, item_count, value = struct.unpack_from("<HHII", payload, off)
        type_size = TYPE_BYTE_SIZES.get(field_type)
        byte_count = type_size * item_count if type_size is not None else None
        data_offset = data_base + value if byte_count is not None and byte_count > 4 else None
        entries.append(
            SdmpEntry(
                tag=tag,
                field_type=field_type,
                count=item_count,
                value_or_offset=value,
                byte_count=byte_count,
                data_offset_from_payload_start=data_offset,
            )
        )
    return entries


def find_radiometric_candidate(jpeg_path: Path) -> tuple[ExtractionCandidate, bytes, list[SdmpEntry]]:
    data = jpeg_path.read_bytes()
    candidates: list[tuple[ExtractionCandidate, bytes, list[SdmpEntry]]] = []
    for marker_start, marker, payload_start, payload in iter_jpeg_segments(data):
        if marker != 0xE3 or not payload.startswith(b"SDMP"):
            continue
        entries = parse_sdmp_ifd(payload)
        by_tag = {entry.tag: entry for entry in entries}
        if not {0, 1, 2, 3, 4, 5}.issubset(by_tag):
            continue
        tag0 = by_tag[0]
        if tag0.data_offset_from_payload_start is None or tag0.byte_count is None:
            continue
        block_rel = tag0.data_offset_from_payload_start
        block_size = tag0.byte_count
        block = payload[block_rel : block_rel + block_size]
        if len(block) < 16:
            continue
        cand = ExtractionCandidate(
            jpeg=str(jpeg_path),
            app3_marker_file_offset=marker_start,
            app3_payload_file_offset=payload_start,
            app3_payload_length=len(payload),
            lpld_file_offset=payload_start + block_rel,
            lpld_payload_offset=block_rel,
            lpld_size_bytes=block_size,
            width_from_sdmp=by_tag[2].value_or_offset if 2 in by_tag else None,
            height_from_sdmp=by_tag[3].value_or_offset if 3 in by_tag else None,
            pixel_format_from_sdmp=by_tag[4].value_or_offset if 4 in by_tag else None,
            first_16_bytes_hex=block[:16].hex(),
        )
        # Prefer the 256x192 format-14 APP3 block.
        if cand.width_from_sdmp == RAW_WIDTH and cand.height_from_sdmp == RAW_HEIGHT:
            candidates.append((cand, block, entries))
    if not candidates:
        raise ValueError(f"no Mini2 radiometric APP3/SDMP candidate found in {jpeg_path}")
    return candidates[-1]


def raw_stats(raw: bytes) -> dict[str, object]:
    vals = struct.unpack("<" + "H" * (len(raw) // 2), raw)
    return {
        "dtype": "little-endian uint16",
        "shape": [RAW_HEIGHT, RAW_WIDTH],
        "min": min(vals),
        "max": max(vals),
        "mean": sum(vals) / len(vals),
        "unique": len(set(vals)),
        "first_16_values": list(vals[:16]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dll-dir", default=str(DLL_DIR_DEFAULT))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--summary-csv", default=None)
    parser.add_argument("jpegs", nargs="+")
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    extractor = MicroJpegUncompresser(Path(args.dll_dir))
    rows: list[dict[str, object]] = []
    for jpeg_arg in args.jpegs:
        jpeg_path = Path(jpeg_arg)
        cand, block, entries = find_radiometric_candidate(jpeg_path)
        raw, dll_evidence = extractor.extract(block)
        stem = jpeg_path.stem
        raw_path = raw_dir / f"{stem}_lpld_raw_u16_256x192.bin"
        raw_path.write_bytes(raw)
        row: dict[str, object] = {
            **asdict(cand),
            "raw_bin": str(raw_path),
            "sdmp_entries": [asdict(e) for e in entries],
            "dll_evidence": dll_evidence,
            "raw_matrix": raw_stats(raw),
        }
        rows.append(row)
        (out_dir / f"{stem}_extract_report.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"{stem}: offset={cand.lpld_file_offset} size={cand.lpld_size_bytes} "
            f"raw={row['raw_matrix']['min']}..{row['raw_matrix']['max']} -> {raw_path}"
        )

    summary_path = Path(args.summary_csv) if args.summary_csv else out_dir / "raw_extraction_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "jpeg",
            "lpld_file_offset",
            "lpld_size_bytes",
            "raw_bin",
            "raw_min",
            "raw_max",
            "raw_mean",
            "raw_unique",
            "get_info_ok",
            "uncompress_ok",
            "raw_info_width",
            "raw_info_height",
            "raw_info_format",
            "raw_info_data_size",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            stats = row["raw_matrix"]
            dll = row["dll_evidence"]
            writer.writerow(
                {
                    "jpeg": row["jpeg"],
                    "lpld_file_offset": row["lpld_file_offset"],
                    "lpld_size_bytes": row["lpld_size_bytes"],
                    "raw_bin": row["raw_bin"],
                    "raw_min": stats["min"],
                    "raw_max": stats["max"],
                    "raw_mean": stats["mean"],
                    "raw_unique": stats["unique"],
                    "get_info_ok": dll["get_info_ok"],
                    "uncompress_ok": dll["uncompress_ok"],
                    "raw_info_width": dll["raw_info_width"],
                    "raw_info_height": dll["raw_info_height"],
                    "raw_info_format": dll["raw_info_format"],
                    "raw_info_data_size": dll["raw_info_data_size"],
                }
            )
    (out_dir / "raw_extraction_summary.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
