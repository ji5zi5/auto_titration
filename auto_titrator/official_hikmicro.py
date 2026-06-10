"""Official HIKMICRO Analyzer DLL bridge for Mini2 raw-to-Celsius conversion.

This module does not fit formulas and does not use Analyzer-exported CSV values
for conversion.  It wraps the official Analyzer MTlib_OL.dll call sequence that
works with Mini2 radiometric JPEG/UVC raw frames:

- MT_Create_INT(width=256, height=192, ...)
- MT_SetConfig(type=6, APP2 tag519 calibration block)
- MT_SetConfig_INT(type=1, traced Analyzer environmental/config keys)
- MT_SetConfig_INT(type=189, APP3 tag1 word 284)
- MT_SetConfig_INT(type=12, APP3 tag1/addline block)
- MT_Process_INT(type=0, point records)

The official output field at point offset +0x10 is an int32 scaled by
64 counts/°C. HIKMICRO Analyzer's exported CSV matrix is the decimal-truncated
view of this continuous Celsius value: floor(temp_c * 10) / 10.
"""

from __future__ import annotations

import ctypes
import io
import json
import os
import struct
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

import numpy as np

from .mini2_live import MINI2_IR_HEIGHT, MINI2_MATRIX_SHAPE, MINI2_UVC_WIDTH, RawToCelsiusConverter


WIDTH = MINI2_UVC_WIDTH
HEIGHT = MINI2_IR_HEIGHT
PIXELS = WIDTH * HEIGHT
POINT_SIZE = 0x24
PROGRAM_FILES_DLL_DIR = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
REPO_VENDOR_DLL_DIR = Path(__file__).resolve().parents[1] / "vendor" / "hikmicro_analyzer"
DLL_DIR_DEFAULT = REPO_VENDOR_DLL_DIR if (REPO_VENDOR_DLL_DIR / "MTlib_OL.dll").exists() else PROGRAM_FILES_DLL_DIR
TYPE_BYTE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}


class OfficialDllUnavailable(RuntimeError):
    """Raised when the official HIKMICRO DLL path cannot be loaded or used."""


@dataclass(frozen=True)
class SdmpEntry:
    tag: int
    field_type: int
    count: int
    value_or_offset: int
    byte_count: int | None
    data_offset_from_payload_start: int | None


@dataclass(frozen=True)
class Mini2OfficialMetadata:
    """Official calibration/config blocks extracted from a Mini2 radiometric JPEG."""

    tag519: bytes
    tag1: bytes
    radiometric_q13: dict[str, int | float]
    source_jpeg: str

    @property
    def tag1_u16_284(self) -> int:
        return int(struct.unpack_from("<H", self.tag1, 284 * 2)[0])

    @property
    def calib_param_type(self) -> int:
        return int(struct.unpack_from("<I", self.tag519, 0x08)[0])

    @property
    def tag1_internal_reflected_c(self) -> float:
        return tag1_internal_reflected_c(self.tag1)

    @classmethod
    def from_jpeg(cls, jpeg: str | Path) -> "Mini2OfficialMetadata":
        path = Path(jpeg)
        tag519 = get_sdmp_block(path, 0xE2, 519)
        tag1 = get_sdmp_block(path, 0xE3, 1, prefer_dims=True)
        if len(tag1) != WIDTH * 2 * 2:
            raise ValueError(f"Mini2 tag1/addline block must be 1024 bytes, got {len(tag1)}")
        return cls(tag519=tag519, tag1=tag1, radiometric_q13=radiometric_q_params(path), source_jpeg=str(path))


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


def get_sdmp_block(jpeg: Path, marker_wanted: int, tag_wanted: int, *, prefer_dims: bool = False) -> bytes:
    found: list[bytes] = []
    for _marker_start, marker, _payload_start, payload in iter_jpeg_segments(jpeg.read_bytes()):
        if marker != marker_wanted or not payload.startswith(b"SDMP"):
            continue
        entries = parse_sdmp_ifd(payload)
        by_tag = {entry.tag: entry for entry in entries}
        entry = by_tag.get(tag_wanted)
        if entry is None or entry.data_offset_from_payload_start is None or entry.byte_count is None:
            continue
        if prefer_dims:
            if by_tag.get(2) is None or by_tag.get(3) is None:
                continue
            if by_tag[2].value_or_offset != WIDTH or by_tag[3].value_or_offset != HEIGHT:
                continue
        start = entry.data_offset_from_payload_start
        found.append(payload[start : start + entry.byte_count])
    if not found:
        raise ValueError(f"missing SDMP marker={marker_wanted:#x} tag={tag_wanted} in {jpeg}")
    return found[-1]


def extract_zipped_json(jpeg: Path, tag_wanted: int) -> dict[str, object]:
    block = get_sdmp_block(jpeg, 0xE3, tag_wanted)
    with zipfile.ZipFile(io.BytesIO(block)) as zf:
        json_names = [name for name in zf.namelist() if name.lower().endswith(".json")]
        if not json_names:
            raise ValueError(f"APP3 tag {tag_wanted} zip has no JSON: {zf.namelist()}")
        return json.loads(zf.read(json_names[0]).decode("utf-8-sig"))


def radiometric_q_params(jpeg: Path) -> dict[str, int | float]:
    data = extract_zipped_json(jpeg, 6)
    r = data["Radiometric"]  # type: ignore[index]
    ta = r["TA"]  # type: ignore[index]
    env = ta["EnvironmentalParameters"]  # type: ignore[index]
    win = ta["IRWindow"]  # type: ignore[index]
    expert = ta["Rules"][0]["Rule_ExpertParameters"]  # type: ignore[index]
    atmospheric_q13 = int(env["AtmosphericTemperature"]["d3"])  # type: ignore[index]
    humidity_q13 = int(round(float(env["Humidity"]) * 8192.0))  # type: ignore[index]
    window_trans_q13 = int(win["OpticsTransmittance"]["d3"])  # type: ignore[index]
    window_temp_milli_c = int(round(int(win["OpticsTemperature"]["d3"]) / 8192.0 * 1000.0))  # type: ignore[index]
    emissivity_q13 = int(expert["Emissivity"]["d3"])  # type: ignore[index]
    reflected_q13 = int(expert["ReflectedTemperature"]["d3"])  # type: ignore[index]
    distance_q13 = int(expert["Distance"]["d3"])  # type: ignore[index]
    return {
        "atmospheric_q13": atmospheric_q13,
        "humidity_q13": humidity_q13,
        "window_trans_q13": window_trans_q13,
        "window_temp_milli_c": window_temp_milli_c,
        "emissivity_q13": emissivity_q13,
        "reflected_q13": reflected_q13,
        "distance_q13": distance_q13,
        "atmospheric_c": atmospheric_q13 / 8192.0,
        "reflected_c": reflected_q13 / 8192.0,
        "distance_m": distance_q13 / 8192.0,
    }


def type1_payload(key: int, value: int) -> bytes:
    return struct.pack("<II", int(key), int(value) & 0xFFFFFFFF)


def tag1_internal_reflected_c(tag1: bytes) -> float:
    """Return Mini2's frame-internal reflected/background temperature estimate.

    This comes from Mini2 addline/tag1 metadata and is used as an official-DLL
    input. It is not derived from Analyzer CSV target temperatures.
    """

    if len(tag1) < 52:
        raise ValueError("tag1/addline block is too short to read reflected temperature fields")
    words = struct.unpack_from("<26H", tag1, 0)
    return float(words[0] + words[1] + words[20] + words[25]) / (4.0 * 50.0)


def align128(x: int) -> int:
    return (x + 0x7F) & ~0x7F


def _addr(buffer: ctypes.Array) -> int:
    return ctypes.addressof(buffer)


def make_mt_memory_descriptor(total_size: int = 0x600000):
    backing = ctypes.create_string_buffer(total_size + 0x400)
    base0 = align128(_addr(backing))
    base1 = align128(base0 + 0x500 + 0x3D00)
    size0 = (base1 - base0) & ~0x7F
    size1 = ((_addr(backing) + len(backing)) - base1) & ~0x7F
    desc = ctypes.create_string_buffer(0x40)
    struct.pack_into("<QII", desc, 0x00, base0, size0, 0x80)
    struct.pack_into("<I", desc, 0x14, 1)
    struct.pack_into("<QII", desc, 0x18, base1, size1, 0x80)
    struct.pack_into("<I", desc, 0x2C, 0)
    return backing, desc


class MtlibRuntime(Protocol):
    def create_handle(self, width: int, height: int) -> object: ...

    def set_config(self, handle: object, config_type: int, data: bytes) -> int: ...

    def process_points(self, handle: object, process_type: int, point_bytes: bytes, count: int) -> tuple[int, bytes]: ...

    def close(self, handle: object) -> None: ...


class CtypesMtlibRuntime:
    """ctypes adapter around HIKMICRO Analyzer's MTlib_OL.dll."""

    def __init__(self, dll_dir: str | Path = DLL_DIR_DEFAULT, *, api_variant: str = "INT") -> None:
        if os.name != "nt":
            raise OfficialDllUnavailable("MTlib_OL.dll is a Windows DLL; run this converter with Windows Python")
        self.dll_dir = Path(dll_dir).resolve()
        self.api_variant = api_variant
        dll_path = self.dll_dir / "MTlib_OL.dll"
        if not dll_path.exists():
            raise OfficialDllUnavailable(f"cannot find official HIKMICRO DLL: {dll_path}")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(self.dll_dir))
        ctypes.windll.kernel32.SetDllDirectoryW(str(self.dll_dir))
        self.dll = ctypes.WinDLL(str(dll_path))
        self._configure_exports()
        self._keepalive: dict[int, list[object]] = {}

    def _configure_exports(self) -> None:
        if self.api_variant not in {"standard", "OL", "INT"}:
            raise OfficialDllUnavailable(f"unsupported MTlib API variant: {self.api_variant}")
        suffix = "" if self.api_variant == "standard" else f"_{self.api_variant}"
        self.MT_GetMemSize = getattr(self.dll, f"MT_GetMemSize{suffix}")
        self.MT_GetMemSize.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.MT_GetMemSize.restype = ctypes.c_int
        self.MT_Create = getattr(self.dll, f"MT_Create{suffix}")
        self.MT_Create.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self.MT_Create.restype = ctypes.c_int
        self.MT_SetConfig = getattr(self.dll, f"MT_SetConfig{suffix}")
        self.MT_SetConfig.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        self.MT_SetConfig.restype = ctypes.c_int
        self.MT_Process = getattr(self.dll, f"MT_Process{suffix}")
        self.MT_Process.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        self.MT_Process.restype = ctypes.c_int

    def create_handle(self, width: int, height: int) -> ctypes.c_void_p:
        params = ctypes.create_string_buffer(0x20)
        struct.pack_into("<IIII", params, 0, int(width), int(height), 1, 1)
        backing, desc = make_mt_memory_descriptor()
        self.MT_GetMemSize(ctypes.byref(params), ctypes.byref(desc))
        backing, desc = make_mt_memory_descriptor()
        handle = ctypes.c_void_p()
        ret = self.MT_Create(ctypes.byref(params), ctypes.byref(desc), ctypes.byref(handle))
        if ret != 0 or not handle.value:
            raise OfficialDllUnavailable(f"MT_Create failed ret={ret} handle={handle.value}")
        self._keepalive[int(handle.value)] = [params, backing, desc]
        return handle

    def set_config(self, handle: object, config_type: int, data: bytes) -> int:
        h = _as_handle(handle)
        data_buffer = ctypes.create_string_buffer(data, len(data))
        self._keepalive.setdefault(int(h.value or 0), []).append(data_buffer)
        return int(self.MT_SetConfig(h, int(config_type), ctypes.cast(data_buffer, ctypes.c_void_p), len(data)))

    def process_points(self, handle: object, process_type: int, point_bytes: bytes, count: int) -> tuple[int, bytes]:
        h = _as_handle(handle)
        points = ctypes.create_string_buffer(point_bytes, len(point_bytes))
        ret = int(self.MT_Process(h, int(process_type), ctypes.cast(points, ctypes.c_void_p), int(count)))
        return ret, bytes(points.raw)

    def close(self, handle: object) -> None:
        h = _as_handle(handle)
        self._keepalive.pop(int(h.value or 0), None)


def _as_handle(handle: object) -> ctypes.c_void_p:
    if isinstance(handle, ctypes.c_void_p):
        return handle
    if isinstance(handle, int):
        return ctypes.c_void_p(handle)
    raise TypeError(f"unsupported MTlib handle type: {type(handle).__name__}")


class OfficialMtlibConverter(RawToCelsiusConverter):
    """RawToCelsiusConverter backed by HIKMICRO's official MTlib_OL.dll."""

    model_name = "official_hikmicro_mtlib_ol"
    calibrated = True

    def __init__(
        self,
        *,
        metadata: Mini2OfficialMetadata,
        runtime: MtlibRuntime | None = None,
        dll_dir: str | Path = DLL_DIR_DEFAULT,
        batch_size: int = 1,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.metadata = metadata
        self.calibration_source = metadata.source_jpeg
        # The traced MT_Process_INT point path returns valid scaled-int Celsius
        # for one point per call. Multi-point calls can return zeroed output on
        # this Mini2/Analyzer DLL path, so force a conservative single-point
        # process loop while still deduplicating repeated raw gray values.
        self.requested_batch_size = int(batch_size)
        self.batch_size = 1
        self.runtime = runtime or CtypesMtlibRuntime(dll_dir)
        self._handle: object | None = None
        self._static_configured = False

    @classmethod
    def from_jpeg(
        cls,
        metadata_jpeg: str | Path,
        *,
        dll_dir: str | Path = DLL_DIR_DEFAULT,
        runtime: MtlibRuntime | None = None,
        batch_size: int = 1,
    ) -> "OfficialMtlibConverter":
        return cls(
            metadata=Mini2OfficialMetadata.from_jpeg(metadata_jpeg),
            dll_dir=dll_dir,
            runtime=runtime,
            batch_size=batch_size,
        )

    def convert(self, raw_matrix: np.ndarray) -> np.ndarray:
        return self.convert_with_addline(raw_matrix, self.metadata.tag1)

    def convert_with_addline(self, raw_matrix: np.ndarray, addline_tag1: bytes | None = None) -> np.ndarray:
        _validate_raw_matrix(raw_matrix)
        tag1 = addline_tag1 or self.metadata.tag1
        raw_flat = raw_matrix.astype("<u2", copy=False).reshape(-1)
        converted = self.convert_values_with_addline(raw_flat, tag1)
        return converted.reshape(MINI2_MATRIX_SHAPE)

    def convert_values_with_addline(self, raw_values: np.ndarray, addline_tag1: bytes | None = None) -> np.ndarray:
        """Convert an arbitrary raw-value vector for the current Mini2 frame.

        This uses the same official MT_Process_INT path as full-frame
        conversion. It is useful for 25fps live ROI features when full-frame
        conversion is not required for every frame.
        """

        raw_values_arr = np.asarray(raw_values)
        if raw_values_arr.dtype.kind not in {"u", "i"}:
            raise ValueError(f"Mini2 raw values must contain integers, got {raw_values_arr.dtype}")
        tag1 = addline_tag1 or self.metadata.tag1
        if len(tag1) != WIDTH * 2 * 2:
            raise ValueError(f"Mini2 addline/tag1 block must be 1024 bytes, got {len(tag1)}")
        handle = self._ensure_handle()
        self._configure_frame(handle, None, tag1)
        # MT_Process_INT receives one raw gray value plus the same embedded
        # expert parameters for every point. Therefore equal raw gray values
        # produce equal official Celsius values in this point API. Process only
        # the unique gray values, then expand back to the full 256x192 frame.
        # This is not a fitted/CSV lookup; every unique value is still computed
        # by HIKMICRO's official DLL for the current frame metadata.
        flat = raw_values_arr.astype("<u2", copy=False).reshape(-1)
        unique_raw, inverse = np.unique(flat, return_inverse=True)
        unique_temps = np.empty(unique_raw.size, dtype=np.float64)
        for start in range(0, unique_raw.size, self.batch_size):
            end = min(start + self.batch_size, unique_raw.size)
            point_bytes = self._pack_points(unique_raw[start:end])
            ret, out_bytes = self.runtime.process_points(handle, 0, point_bytes, end - start)
            if ret != 0:
                raise OfficialDllUnavailable(f"MT_Process failed ret={ret} at unique raw batch starting {start}")
            unique_temps[start:end] = self._read_scaled_int_celsius(out_bytes, end - start)
        return unique_temps[inverse].reshape(raw_values_arr.shape)

    def close(self) -> None:
        if self._handle is not None:
            self.runtime.close(self._handle)
            self._handle = None
            self._static_configured = False

    def _ensure_handle(self) -> object:
        if self._handle is None:
            self._handle = self.runtime.create_handle(WIDTH, HEIGHT)
            self._configure_static(self._handle)
        return self._handle

    def _configure_static(self, handle: object) -> None:
        if self._static_configured:
            return
        params = self.metadata.radiometric_q13
        static_items = [
            (6, self.metadata.tag519, "APP2 tag519 calibration"),
            (1, type1_payload(13, 0), "key13=0"),
            (1, type1_payload(45, 1), "key45=1"),
            (1, type1_payload(29, 0), "key29=0"),
            (1, type1_payload(55, 0), "key55=0"),
            (1, type1_payload(14, 0), "key14=0"),
            (1, type1_payload(5, int(params["atmospheric_q13"])), "key5 atmospheric q13"),
            (1, type1_payload(6, int(params["humidity_q13"])), "key6 humidity q13"),
            (1, type1_payload(20, int(params["window_trans_q13"])), "key20 window transmittance q13"),
            (1, type1_payload(21, int(params["window_temp_milli_c"])), "key21 window temperature milli C"),
            (1, type1_payload(152, 1), "key152=1"),
        ]
        for config_type, data, name in static_items:
            ret = self.runtime.set_config(handle, config_type, data)
            if ret != 0 and not (name == "key55=0" and ret == -18):
                raise OfficialDllUnavailable(f"MT_SetConfig_INT failed for {name}: ret={ret}")
        self._static_configured = True

    def _configure_frame(self, handle: object, raw_matrix: np.ndarray | None, tag1: bytes) -> None:
        # raw_matrix is validated and consumed through per-point gray values.
        # The traced Analyzer path only needs per-frame addline metadata here.
        _ = raw_matrix
        tag1_u16_284 = int(struct.unpack_from("<H", tag1, 284 * 2)[0])
        frame_items = [
            (189, struct.pack("<IIII", tag1_u16_284, 0, 0, 0), "type189 tag1_u16[284]"),
            (12, tag1, "APP3 tag1 addline"),
        ]
        for config_type, data, name in frame_items:
            ret = self.runtime.set_config(handle, config_type, data)
            if ret != 0:
                raise OfficialDllUnavailable(f"MT_SetConfig_INT failed for {name}: ret={ret}")

    def _pack_points(self, raw_values: np.ndarray) -> bytes:
        params = self.metadata.radiometric_q13
        points = np.zeros((len(raw_values), POINT_SIZE), dtype=np.uint8)
        points[:, 0x04:0x08].view("<i4").reshape(-1)[:] = raw_values.astype(np.int32, copy=False)
        points[:, 0x14:0x18].view("<i4").reshape(-1)[:] = int(params["emissivity_q13"])
        points[:, 0x18:0x1C].view("<i4").reshape(-1)[:] = int(params["reflected_q13"])
        points[:, 0x1C:0x20].view("<i4").reshape(-1)[:] = int(params["distance_q13"])
        return points.tobytes()

    @staticmethod
    def _read_scaled_int_celsius(point_bytes: bytes, count: int) -> np.ndarray:
        points = np.frombuffer(point_bytes, dtype=np.uint8).reshape(count, POINT_SIZE)
        out_i32 = points[:, 0x10:0x14].copy().view("<i4").reshape(-1)
        return out_i32.astype(np.float64) / 64.0


def analyzer_csv_truncate_0p1(temperature_c: np.ndarray) -> np.ndarray:
    """Return HIKMICRO Analyzer CSV-style one-decimal truncated temperatures."""

    return np.floor(temperature_c.astype(np.float64, copy=False) * 10.0) / 10.0


def _validate_raw_matrix(raw_matrix: np.ndarray) -> None:
    if raw_matrix.shape != MINI2_MATRIX_SHAPE:
        raise ValueError(f"Mini2 raw matrix must have shape {MINI2_MATRIX_SHAPE}, got {raw_matrix.shape}")
    if raw_matrix.dtype.kind not in {"u", "i"}:
        raise ValueError(f"Mini2 raw matrix must contain integer raw values, got {raw_matrix.dtype}")


class OfficialMtlibWorkerConverter(RawToCelsiusConverter):
    """Subprocess bridge for using Windows Python/MTlib from another process.

    The worker must run ``tools/mini2_official_mtlib_worker_win.py`` or another
    command implementing the same length-prefixed binary protocol.
    """

    model_name = "official_hikmicro_mtlib_worker"
    calibrated = True

    def __init__(self, command: list[str], *, calibration_source: str = "official_mtlib_worker") -> None:
        if not command:
            raise ValueError("worker command must not be empty")
        self.command = command
        self.calibration_source = calibration_source
        self._process: subprocess.Popen[bytes] | None = None

    def convert(self, raw_matrix: np.ndarray) -> np.ndarray:
        return self.convert_with_addline(raw_matrix, None)

    def convert_with_addline(self, raw_matrix: np.ndarray, addline_tag1: bytes | None = None) -> np.ndarray:
        _validate_raw_matrix(raw_matrix)
        process = self._ensure_process()
        assert process.stdin is not None and process.stdout is not None
        raw_bytes = raw_matrix.astype("<u2", copy=False).tobytes()
        addline = addline_tag1 or b""
        process.stdin.write(struct.pack("<II", len(raw_bytes), len(addline)))
        process.stdin.write(raw_bytes)
        process.stdin.write(addline)
        process.stdin.flush()
        header = _read_exact(process.stdout, 8)
        if len(header) != 8:
            detail = ""
            if process.poll() is not None and process.stderr is not None:
                detail = process.stderr.read().decode("utf-8", errors="replace").strip()
            suffix = f": {detail}" if detail else ""
            raise OfficialDllUnavailable(f"official MTlib worker closed before returning a frame{suffix}")
        status, payload_len = struct.unpack("<II", header)
        payload = _read_exact(process.stdout, payload_len)
        if len(payload) != payload_len:
            raise OfficialDllUnavailable("official MTlib worker returned a truncated payload")
        if status != 0:
            raise OfficialDllUnavailable(payload.decode("utf-8", errors="replace"))
        matrix = np.frombuffer(payload, dtype="<f8").reshape(MINI2_MATRIX_SHAPE).copy()
        return matrix

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        finally:
            if process.poll() is None:
                process.terminate()

    def _ensure_process(self) -> subprocess.Popen[bytes]:
        if self._process is None:
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        return self._process


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def worker_loop(converter: OfficialMtlibConverter, stdin: BinaryIO, stdout: BinaryIO) -> None:
    """Length-prefixed worker protocol used by OfficialMtlibWorkerConverter."""

    while True:
        header = _read_exact(stdin, 8)
        if not header:
            return
        if len(header) != 8:
            _write_worker_error(stdout, "truncated request header")
            return
        raw_len, addline_len = struct.unpack("<II", header)
        raw_bytes = _read_exact(stdin, raw_len)
        addline = _read_exact(stdin, addline_len) if addline_len else None
        try:
            if raw_len != PIXELS * 2:
                raise ValueError(f"expected {PIXELS * 2} raw bytes, got {raw_len}")
            raw_matrix = np.frombuffer(raw_bytes, dtype="<u2").reshape(MINI2_MATRIX_SHAPE).copy()
            matrix = converter.convert_with_addline(raw_matrix, addline)
            payload = matrix.astype("<f8", copy=False).tobytes()
            stdout.write(struct.pack("<II", 0, len(payload)))
            stdout.write(payload)
            stdout.flush()
        except Exception as exc:  # pragma: no cover - exercised by integration/real worker use.
            _write_worker_error(stdout, f"{type(exc).__name__}: {exc}")


def _write_worker_error(stdout: BinaryIO, message: str) -> None:
    payload = message.encode("utf-8", errors="replace")
    stdout.write(struct.pack("<II", 1, len(payload)))
    stdout.write(payload)
    stdout.flush()
