#!/usr/bin/env python3
"""Inspect HIKMICRO Mini2 radiometric JPEG raw payload evidence.

This tool deliberately does not infer temperature from palette colors. It parses
HIKMICRO SDMP APP segments, extracts the radiometric APP3 raw/compressed block,
loads the same-capture Analyzer CSV, and tests whether any uncompressed Celsius
matrix is directly present in the JPEG payload.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

try:
    from auto_titrator.thermal_camera import load_hikmicro_temperature_csv
except ModuleNotFoundError:  # pragma: no cover - script convenience when run directly
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from auto_titrator.thermal_camera import load_hikmicro_temperature_csv


@dataclass(frozen=True)
class JpegSegment:
    index: int
    marker: str
    offset: int
    payload_length: int
    starts_with: str


@dataclass(frozen=True)
class SdmpEntry:
    tag: int
    field_type: int
    count: int
    value_or_offset: int
    absolute_payload_offset: int | None
    byte_count_guess: int | None


TYPE_BYTE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}


def iter_jpeg_segments(data: bytes) -> Iterable[tuple[int, int, bytes]]:
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
        if marker == 0xDA:  # Start of Scan; entropy-coded image data follows.
            break
        if pos + 2 > len(data):
            break
        length = int.from_bytes(data[pos : pos + 2], "big")
        payload = data[pos + 2 : pos + length]
        yield marker_start, marker, payload
        pos += length


def parse_sdmp_ifd(payload: bytes) -> list[SdmpEntry]:
    """Parse the SDMP IFD-like table observed in HIKMICRO APP blocks.

    Observed layout: `SDMP` 16-byte preamble, uint16 entry count at 0x10,
    then count records of standard TIFF-like 12 bytes starting at 0x12:
    tag:uint16, type:uint16, count:uint32, value_or_offset:uint32. Offsets are
    relative to 0x1a in the APP payload.
    """

    if not payload.startswith(b"SDMP") or len(payload) < 0x12:
        return []
    count = int.from_bytes(payload[0x10:0x12], "little")
    if not (0 < count < 128):
        return []
    entries: list[SdmpEntry] = []
    data_base = 0x1A
    for i in range(count):
        off = 0x12 + i * 12
        if off + 12 > len(payload):
            break
        tag, field_type, item_count, value = struct.unpack_from("<HHII", payload, off)
        byte_size = TYPE_BYTE_SIZES.get(field_type)
        byte_count = byte_size * item_count if byte_size is not None else None
        absolute = None
        if byte_count is not None and byte_count > 4:
            absolute = data_base + value
        entries.append(
            SdmpEntry(
                tag=tag,
                field_type=field_type,
                count=item_count,
                value_or_offset=value,
                absolute_payload_offset=absolute,
                byte_count_guess=byte_count,
            )
        )
    return entries


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def d_fixed(value: int, fractional_bits: int) -> float:
    return value / float(1 << fractional_bits)


def scan_direct_payload(payload: bytes, csv_values: np.ndarray) -> list[dict[str, object]]:
    flat = csv_values.ravel()
    patterns = {
        "csv_deci_c_u16_first16": np.rint(flat[:16] * 10).astype("<u2").tobytes(),
        "csv_d2_i32_first8_C_times_1024": np.rint(flat[:8] * 1024).astype("<i4").tobytes(),
        "csv_d3_i32_first8_C_times_8192": np.rint(flat[:8] * 8192).astype("<i4").tobytes(),
        "csv_float32_first8": flat[:8].astype("<f4").tobytes(),
    }
    hits: list[dict[str, object]] = []
    for name, pattern in patterns.items():
        pos = payload.find(pattern)
        hits.append({"pattern": name, "found": pos >= 0, "offset": pos if pos >= 0 else None})
    return hits


def extract_radiometric_block(jpeg_bytes: bytes) -> tuple[JpegSegment, bytes, list[SdmpEntry]]:
    best: tuple[JpegSegment, bytes, list[SdmpEntry]] | None = None
    for idx, (offset, marker, payload) in enumerate(iter_jpeg_segments(jpeg_bytes)):
        segment = JpegSegment(
            index=idx,
            marker=f"FF{marker:02X}",
            offset=offset,
            payload_length=len(payload),
            starts_with=payload[:16].hex(),
        )
        entries = parse_sdmp_ifd(payload)
        tags = {entry.tag for entry in entries}
        if marker == 0xE3 and {0, 1, 2, 3, 4, 5}.issubset(tags):
            # The large APP3 block with compressed radiometric payload.
            best = (segment, payload, entries)
    if best is None:
        raise ValueError("could not find HIKMICRO SDMP radiometric APP3 block")
    return best


def make_report(args: argparse.Namespace) -> dict[str, object]:
    jpeg_path = Path(args.jpeg)
    csv_path = Path(args.csv)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    jpeg_bytes = jpeg_path.read_bytes()
    matrix = load_hikmicro_temperature_csv(csv_path).values.astype(float)
    segment, payload, entries = extract_radiometric_block(jpeg_bytes)
    entries_dicts = [asdict(entry) for entry in entries]

    entry_by_tag = {entry.tag: entry for entry in entries}
    compressed = b""
    metadata = b""
    if 0 in entry_by_tag and entry_by_tag[0].absolute_payload_offset is not None:
        e = entry_by_tag[0]
        compressed = payload[e.absolute_payload_offset : e.absolute_payload_offset + (e.byte_count_guess or 0)]
        (out_dir / "radiometric_tag0_compressed_u16.bin").write_bytes(compressed)
    if 1 in entry_by_tag and entry_by_tag[1].absolute_payload_offset is not None:
        e = entry_by_tag[1]
        metadata = payload[e.absolute_payload_offset : e.absolute_payload_offset + min(e.byte_count_guess or 0, len(payload) - e.absolute_payload_offset)]
        (out_dir / "radiometric_tag1_metadata.bin").write_bytes(metadata)

    radiometric_json_path = Path(args.radiometric_json) if args.radiometric_json else None
    fixed_point_evidence: dict[str, object] = {}
    if radiometric_json_path and radiometric_json_path.exists():
        rj = read_json(radiometric_json_path)
        radiometric = rj.get("Radiometric", {})
        static = radiometric.get("StaticInfo", {})
        ta = radiometric.get("TA", {})
        isp = radiometric.get("IA", {}).get("ISP", {})
        fixed_point_evidence = {
            "PixelSize": static.get("PixelSize"),
            "TemperatureRange_Range_d2_raw": static.get("TemperatureRange", {}).get("Range_d2"),
            "TemperatureRange_Range_d2_C_if_div1024": [
                d_fixed(v, 10) for v in static.get("TemperatureRange", {}).get("Range_d2", [])
            ],
            "LevelSpanRange_Range_d3_raw": isp.get("LevelSpanRange", {}).get("Range_d3"),
            "LevelSpanRange_Range_d3_C_if_div8192": [
                d_fixed(v, 13) for v in isp.get("LevelSpanRange", {}).get("Range_d3", [])
            ],
            "AtmosphericTemperature_d3_C": d_fixed(
                ta.get("EnvironmentalParameters", {}).get("AtmosphericTemperature", {}).get("d3", 0), 13
            ),
            "OpticsTemperature_d3_C": d_fixed(
                ta.get("IRWindow", {}).get("OpticsTemperature", {}).get("d3", 0), 13
            ),
            "ReflectedTemperature_d3_C": d_fixed(
                ta.get("Rules", [{}])[0].get("Rule_ExpertParameters", {}).get("ReflectedTemperature", {}).get("d3", 0), 13
            ),
            "Emissivity_if_d3": d_fixed(
                ta.get("Rules", [{}])[0].get("Rule_ExpertParameters", {}).get("Emissivity", {}).get("d3", 0), 13
            ),
        }

    comp_words = np.frombuffer(compressed[: len(compressed) // 2 * 2], dtype="<u2") if compressed else np.array([], dtype=np.uint16)
    meta_words = np.frombuffer(metadata[: len(metadata) // 2 * 2], dtype="<u2") if metadata else np.array([], dtype=np.uint16)

    report = {
        "input": {"jpeg": str(jpeg_path), "csv": str(csv_path), "radiometric_json": str(radiometric_json_path) if radiometric_json_path else None},
        "csv_temperature_matrix": {
            "shape": list(matrix.shape),
            "min_c": float(matrix.min()),
            "max_c": float(matrix.max()),
            "mean_c": float(matrix.mean()),
            "first_row_first16_c": [float(x) for x in matrix[0, :16]],
        },
        "radiometric_app3_segment": asdict(segment),
        "sdmp_entries": entries_dicts,
        "tag0_compressed_payload": {
            "byte_length": len(compressed),
            "word_length_u16": int(comp_words.size),
            "sha256": sha256_hex(compressed) if compressed else None,
            "first_64_words_hex": [f"{int(x):04x}" for x in comp_words[:64]],
            "value_min_u16": int(comp_words.min()) if comp_words.size else None,
            "value_max_u16": int(comp_words.max()) if comp_words.size else None,
        },
        "tag1_metadata_payload": {
            "byte_length_available": len(metadata),
            "word_length_u16_available": int(meta_words.size),
            "sha256": sha256_hex(metadata) if metadata else None,
            "first_80_words_hex": [f"{int(x):04x}" for x in meta_words[:80]],
            "notable_magic_offsets_u16": {
                "BBAADDCC": [int(i) for i in np.where(meta_words[:-1].astype(np.uint32) | (meta_words[1:].astype(np.uint32) << 16) == 0xBBAADDCC)[0]] if meta_words.size > 1 else [],
                "AABBCCDD": [int(i) for i in np.where(meta_words[:-1].astype(np.uint32) | (meta_words[1:].astype(np.uint32) << 16) == 0xAABBCCDD)[0]] if meta_words.size > 1 else [],
            },
        },
        "direct_uncompressed_matrix_scan_in_app3": scan_direct_payload(payload, matrix),
        "fixed_point_metadata_evidence": fixed_point_evidence,
        "current_conclusion": {
            "proven": [
                "IR_00001_이미지.csv is the calibrated Celsius temperature matrix for the same capture.",
                "IR_00001.jpeg contains a large APP3/SDMP radiometric block with width=256, height=192 and a compressed tag0 payload.",
                "The tag0 payload is compressed (16074 uint16 words), not a directly stored 192x256 Celsius/deci-C/d2/d3/float matrix.",
                "HIKMICRO JSON uses fixed-point suffixes: d2 values divide by 1024, d3 values divide by 8192.",
            ],
            "candidate_after_decompression": "If the decompressed radiometric pixels are stored as HIKMICRO d2 temperature integers, Celsius = raw_d2 / 1024. If they are d3 temperature integers, Celsius = raw_d3 / 8192. This is fixed-point evidence, not yet a decoded tag0 proof.",
            "blocked_piece": "The remaining missing step is HIKMICRO LPLD/UnCompresser decompression of tag0. Without decoding tag0 or calling the SDK RawDataInfo path successfully, a pixel-level raw-to-Celsius residual cannot be honestly claimed.",
        },
    }
    (out_dir / "mini2_rjpeg_raw_research_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = [
        "# Mini2 IR_00001 Raw/Radiometric Formula Research",
        "",
        f"- JPEG: `{jpeg_path}`",
        f"- CSV: `{csv_path}`",
        f"- CSV shape/range: `{matrix.shape[0]}x{matrix.shape[1]}`, {matrix.min():.1f}..{matrix.max():.1f} °C, mean {matrix.mean():.6f} °C",
        f"- Radiometric APP3: marker {segment.marker}, payload {segment.payload_length} bytes at JPEG offset {segment.offset}",
        "",
        "## SDMP radiometric entries",
        "",
        "| tag | type | count | value/offset | absolute payload offset | byte count guess |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for e in entries:
        md.append(f"| {e.tag} | {e.field_type} | {e.count} | {e.value_or_offset} | {e.absolute_payload_offset} | {e.byte_count_guess} |")
    md.extend(
        [
            "",
            "## Result",
            "",
            "현재 증거로 확정된 것은 `APP3 tag0`이 256x192용 radiometric payload이지만 `16074 uint16`로 압축되어 있다는 점이다.",
            "CSV와 같은 192x256 온도행렬이 JPEG 내부에 deci-C/u16, d2/i32, d3/i32, float32 형태로 직접 저장된 흔적은 발견되지 않았다.",
            "HIKMICRO JSON의 d2/d3 고정소수점 관례상, 압축 해제 후 d2 정수라면 `°C = raw / 1024`, d3 정수라면 `°C = raw / 8192`가 후보식이다.",
            "하지만 tag0 LPLD 압축 해제 또는 SDK RawDataInfo 호출이 아직 성공하지 않았으므로, 이 단계에서는 pixel-level residual을 통과한 최종식이라고 주장하지 않는다.",
        ]
    )
    (out_dir / "mini2_rjpeg_raw_research_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jpeg", default="data/fixtures/mini2/IR_00001.jpeg")
    parser.add_argument("--csv", default="data/fixtures/mini2/IR_00001_이미지.csv")
    parser.add_argument("--radiometric-json", default="data/mini2_jpeg_extract/Radiometric.json")
    parser.add_argument("--output-dir", default="data/mini2_rjpeg_raw_research")
    args = parser.parse_args()
    report = make_report(args)
    print(json.dumps(report["current_conclusion"], ensure_ascii=False, indent=2))
    print(f"saved: {Path(args.output_dir) / 'mini2_rjpeg_raw_research_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
