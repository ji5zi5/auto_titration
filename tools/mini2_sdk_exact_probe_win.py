#!/usr/bin/env python3
"""Probe HIKMICRO Analyzer DLLs for an SDK-equivalent raw gray -> Celsius path.

Run with Windows Python. This is intentionally diagnostic: it tries exported
factory/conversion functions with the real IR_0000*.jpeg files and records
which call paths return usable temperature values. It does not use the exported
CSV answer matrix to build a lookup table.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path


DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")


class BareBlock(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.c_void_p),
        ("size", ctypes.c_uint32),
        ("pad", ctypes.c_uint32),
    ]


class Resolution(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
    ]


@dataclass(frozen=True)
class Segment:
    marker_start: int
    marker: int
    payload_start: int
    payload: bytes


def iter_jpeg_segments(data: bytes):
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("not a JPEG")
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
        yield Segment(marker_start, marker, payload_start, data[payload_start:payload_end])
        pos = payload_end


def parse_sdmp_entries(payload: bytes):
    if not payload.startswith(b"SDMP") or len(payload) < 0x12:
        return []
    count = int.from_bytes(payload[0x10:0x12], "little")
    if not (0 < count < 256):
        return []
    out = []
    type_sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}
    for i in range(count):
        off = 0x12 + 12 * i
        if off + 12 > len(payload):
            break
        tag, typ, item_count, value = struct.unpack_from("<HHII", payload, off)
        size = type_sizes.get(typ, 0) * item_count
        data_off = 0x10 + value if size > 4 else None
        out.append(
            {
                "tag": tag,
                "type": typ,
                "count": item_count,
                "value": value,
                "byte_count": size,
                "data_off": data_off,
            }
        )
    return out


def collect_blocks(jpeg: Path) -> dict[str, bytes]:
    data = jpeg.read_bytes()
    blocks: dict[str, bytes] = {
        "full_jpeg": data,
        "full_without_soi": data[2:],
    }
    for idx, seg in enumerate(iter_jpeg_segments(data)):
        label = f"seg{idx:02d}_APP{seg.marker - 0xE0:x}_payload" if 0xE0 <= seg.marker <= 0xEF else f"seg{idx:02d}_marker_{seg.marker:02x}_payload"
        blocks[label] = seg.payload
        blocks[label + "_with_marker_len"] = data[seg.marker_start : seg.payload_start + len(seg.payload)]
        if seg.marker == 0xE3 and seg.payload.startswith(b"SDMP"):
            entries = parse_sdmp_entries(seg.payload)
            for e in entries:
                off = e["data_off"]
                size = e["byte_count"]
                if off is not None and size and off + size <= len(seg.payload):
                    blocks[f"{label}_tag{e['tag']}_data"] = seg.payload[off : off + size]
    return blocks


def add_dll_dir(dll_dir: Path) -> None:
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(dll_dir))
    ctypes.windll.kernel32.SetDllDirectoryW(str(dll_dir))


def get_proc(dll: ctypes.CDLL, name: bytes):
    k32 = ctypes.windll.kernel32
    k32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    k32.GetProcAddress.restype = ctypes.c_void_p
    return k32.GetProcAddress(dll._handle, name)


def make_block(data: bytes):
    # Keep buffer alive next to BareBlock.
    buf = ctypes.create_string_buffer(data)
    block = BareBlock(ctypes.cast(buf, ctypes.c_void_p), len(data), 0)
    return buf, block


def hexdump_words(buf: bytes, max_len: int = 128) -> str:
    words = [f"{int.from_bytes(buf[i:i+4], 'little'):08x}" for i in range(0, min(max_len, len(buf)), 4)]
    return " ".join(words)


def try_get_raw_data_info(get_raw_info, ctx: int):
    out = ctypes.create_string_buffer(0x400)
    ok = bool(get_raw_info(ctypes.byref(out), ctypes.c_void_p(ctx)))
    return ok, bytes(out.raw)


def try_gray_to_temp(gray_to_temp, ctx: int, gray_values: list[int]):
    vals = []
    for gray in gray_values:
        out = ctypes.c_int32(-999999)
        try:
            ok = bool(gray_to_temp(ctypes.byref(out), ctypes.c_uint16(gray), ctypes.c_void_p(ctx)))
            vals.append({"gray": gray, "ok": ok, "out_int": int(out.value)})
        except Exception as exc:
            vals.append({"gray": gray, "exception": repr(exc)})
    return vals


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, default=Path("data/fixtures/mini2/IR_00001.jpeg"))
    ap.add_argument("--out", type=Path, default=Path("data/mini2_sdk_exact_probe"))
    args = ap.parse_args(argv)

    add_dll_dir(args.dll_dir)
    microjpeg = ctypes.WinDLL(str(args.dll_dir / "MicroJPEG_Release_x64.dll"))
    microjita = ctypes.WinDLL(str(args.dll_dir / "MicroJITA_Release_x64.dll"))

    names = {
        "createImage": b"?createImage@ImageFactory@MicroSDK@@SAPEAVBaseImage@2@AEBUBareBlock@2@W4FileType@2@@Z",
        "createMicroRImageV1": b"?createMicroRImageV1@ImageFactory@MicroSDK@@SAPEAVMicroRImageV1@2@AEBUBareBlock@2@@Z",
        "createMicroRImageV2": b"?createMicroRImageV2@ImageFactory@MicroSDK@@SAPEAVMicroRImageV2@2@AEBUBareBlock@2@@Z",
        "createStandardRImage": b"?createStandardRImage@ImageFactory@MicroSDK@@SAPEAVStandardRImage@2@AEBUBareBlock@2@@Z",
        "createFromOfflineV1AddInfoRawPtr": b"?createFromOfflineV1AddInfoRawPtr@ImageFactory@MicroSDK@@SAPEAVMicroRImageV1@2@AEBUBareBlock@2@AEBUmResolution@2@@Z",
        "getRawDataInfo": b"?getRawDataInfo@MicroSDK@@YA_NAEAURawDataInfo@1@QEAX@Z",
        "grayToTemperature": b"?grayToTemperature@MicroSDK@@YA_NAEAHGQEAX@Z",
        "temperatureToGray": b"?temperatureToGray@MicroSDK@@YA_NAEAGHQEAX@Z",
    }
    addrs = {k: get_proc(microjpeg if k.startswith("create") else microjita, v) for k, v in names.items()}
    missing = {k: v.decode() for k, v in names.items() if not addrs[k]}
    if missing:
        print("missing exports:", missing)

    create_image = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock), ctypes.c_int32)(addrs["createImage"])
    create_v1 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock))(addrs["createMicroRImageV1"])
    create_v2 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock))(addrs["createMicroRImageV2"])
    create_std = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock))(addrs["createStandardRImage"])
    create_offline = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock), ctypes.POINTER(Resolution))(addrs["createFromOfflineV1AddInfoRawPtr"])
    get_raw_info = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(addrs["getRawDataInfo"])
    gray_to_temp = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_uint16, ctypes.c_void_p)(addrs["grayToTemperature"])
    temp_to_gray = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p)(addrs["temperatureToGray"])

    # Many SDK factory functions throw C++ exceptions for the wrong binary
    # block type. Keep the default probe conservative so a bad block does not
    # terminate the whole run before we learn anything.
    all_blocks = collect_blocks(args.jpeg)
    blocks = {
        "full_jpeg": all_blocks["full_jpeg"],
    }
    if os.environ.get("MINI2_PROBE_SDMP_BLOCKS") == "1":
        for name, blob in all_blocks.items():
            if "_APP3_payload_tag" in name or (name.endswith("_APP3_payload") and blob.startswith(b"SDMP")):
                blocks[name] = blob
    args.out.mkdir(parents=True, exist_ok=True)
    summary = {
        "dll_dir": str(args.dll_dir),
        "jpeg": str(args.jpeg),
        "exports": {k: hex(v) if v else None for k, v in addrs.items()},
        "attempts": [],
    }

    gray_values = [5000, 5020, 5038, 5050, 5109, 5150, 5200, 5300, 5364, 5417]
    factory_specs = []
    for file_type in range(0, 16):
        factory_specs.append((f"createImage_filetype_{file_type}", lambda b, ft=file_type: create_image(ctypes.byref(b), ft)))
    factory_specs += [
        ("createMicroRImageV1", lambda b: create_v1(ctypes.byref(b))),
        ("createMicroRImageV2", lambda b: create_v2(ctypes.byref(b))),
        ("createStandardRImage", lambda b: create_std(ctypes.byref(b))),
    ]
    reses = [Resolution(256, 192), Resolution(192, 256), Resolution(640, 512), Resolution(0, 0)]
    for ri, res in enumerate(reses):
        factory_specs.append((f"createOfflineAddInfo_{res.width}x{res.height}", lambda b, r=res: create_offline(ctypes.byref(b), ctypes.byref(r))))

    for block_name, block_data in blocks.items():
        if not block_data:
            continue
        # Avoid huge/noisy duplicates except the full JPEG and SDMP/tag blocks.
        if len(block_data) > 500_000:
            continue
        for factory_name, factory in factory_specs:
            if block_name == "full_jpeg":
                # Only createImage is expected to accept a full JPEG. The
                # MicroRImage-specific factories can throw on normal JPEG
                # streams and should be tested separately.
                if not factory_name.startswith("createImage_filetype_"):
                    continue
            else:
                # Conversely, createImage/MicroRImage-specific factories expect
                # JPEG streams and can terminate the process on arbitrary SDMP
                # payloads. For embedded APP3/tag blocks, only test the
                # OfflineV1 AddInfo factory.
                if not factory_name.startswith("createOfflineAddInfo_"):
                    continue
            buf, bb = make_block(block_data)
            attempt = {
                "block": block_name,
                "block_len": len(block_data),
                "factory": factory_name,
                "ptr": None,
                "getRawDataInfo_ok": None,
                "raw_info_prefix_u32_hex": None,
                "grayToTemperature": None,
                "temperatureToGray": None,
            }
            try:
                ptr = factory(bb)
                attempt["ptr"] = hex(int(ptr)) if ptr else None
                if ptr:
                    ok, raw_info = try_get_raw_data_info(get_raw_info, int(ptr))
                    attempt["getRawDataInfo_ok"] = ok
                    attempt["raw_info_prefix_u32_hex"] = hexdump_words(raw_info, 160)
                    attempt["grayToTemperature"] = try_gray_to_temp(gray_to_temp, int(ptr), gray_values)
                    tg = []
                    for temp_int in [198, 200, 222, 250, 300, 339, 356, 2000, 2220, 3390]:
                        outg = ctypes.c_uint16(0)
                        try:
                            ok2 = bool(temp_to_gray(ctypes.byref(outg), ctypes.c_int32(temp_int), ctypes.c_void_p(int(ptr))))
                            tg.append({"temp_int": temp_int, "ok": ok2, "gray": int(outg.value)})
                        except Exception as exc:
                            tg.append({"temp_int": temp_int, "exception": repr(exc)})
                    attempt["temperatureToGray"] = tg
            except Exception as exc:
                attempt["exception"] = repr(exc)
            finally:
                # No destructor call: this is a short-lived diagnostic process.
                pass
            if attempt.get("ptr") or attempt.get("exception"):
                summary["attempts"].append(attempt)
                print(json.dumps(attempt, ensure_ascii=False)[:1200])

    out_path = args.out / (args.jpeg.stem + "_sdk_exact_probe.json")
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
