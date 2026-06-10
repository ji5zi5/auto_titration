"""Live HIKMICRO Mini2 UVC raw-frame temperature pipeline.

This module is intentionally strict: a 256x192 Celsius matrix is produced only
when an explicit raw->Celsius converter is supplied. Raw uint16 frames are never
silently treated as temperatures.
"""

from __future__ import annotations

import csv
import json
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

import numpy as np

from .color_analysis import Roi


MINI2_UVC_WIDTH = 256
MINI2_UVC_HEIGHT = 344
MINI2_IR_HEIGHT = 192
MINI2_FRAME_RATE_HZ = 25.0
MINI2_INPUT_FORMAT = "yuyv422"
MINI2_RAW_FRAME_BYTES = MINI2_UVC_WIDTH * MINI2_UVC_HEIGHT * 2
MINI2_MATRIX_SHAPE = (MINI2_IR_HEIGHT, MINI2_UVC_WIDTH)


class ThermalConversionUnavailable(RuntimeError):
    """Raised when a Celsius matrix is requested without a valid converter."""


class RawToCelsiusConverter(Protocol):
    """Convert Mini2 raw uint16 matrices into Celsius matrices."""

    model_name: str
    calibrated: bool
    calibration_source: str

    def convert(self, raw_matrix: np.ndarray) -> np.ndarray:
        """Return a float Celsius matrix with the same shape as ``raw_matrix``."""


@dataclass(frozen=True)
class Mini2RawFrameParts:
    """Decoded pieces from one 256x344 Mini2 UVC raw frame.

    The upper 256x192 area is the per-pixel raw matrix.  The immediately
    following two lines are the 1024-byte Mini2 addline/tag1 block used by the
    official HIKMICRO MTlib converter for frame-specific configuration.
    """

    raw_matrix: np.ndarray
    addline_tag1: bytes
    full_frame_u16: np.ndarray


def expected_raw_frame_bytes(width: int = MINI2_UVC_WIDTH, height: int = MINI2_UVC_HEIGHT) -> int:
    return width * height * 2


def extract_mini2_raw_matrix(
    raw_bytes: bytes,
    *,
    width: int = MINI2_UVC_WIDTH,
    height: int = MINI2_UVC_HEIGHT,
    matrix_height: int = MINI2_IR_HEIGHT,
) -> np.ndarray:
    """Extract the top 256x192 raw uint16 matrix from one 256x344 UVC frame."""

    expected = expected_raw_frame_bytes(width, height)
    if len(raw_bytes) != expected:
        raise ValueError(f"expected {expected} bytes for {width}x{height} uint16 raw frame, got {len(raw_bytes)}")
    if matrix_height <= 0 or matrix_height > height:
        raise ValueError(f"matrix_height must be between 1 and {height}, got {matrix_height}")
    full_frame = np.frombuffer(raw_bytes, dtype="<u2").reshape(height, width)
    return full_frame[:matrix_height, :].copy()


def extract_mini2_frame_parts(
    raw_bytes: bytes,
    *,
    width: int = MINI2_UVC_WIDTH,
    height: int = MINI2_UVC_HEIGHT,
    matrix_height: int = MINI2_IR_HEIGHT,
) -> Mini2RawFrameParts:
    """Extract raw pixels plus the official 1024-byte addline block.

    Mini2 V2 exposes a 256x344 YUYV/raw UVC frame.  Existing evidence shows the
    first 192 rows are the radiometric raw matrix and rows 192-193 are the same
    APP3 tag1/addline block that Analyzer passes to MT_SetConfig(type=12).
    """

    expected = expected_raw_frame_bytes(width, height)
    if len(raw_bytes) != expected:
        raise ValueError(f"expected {expected} bytes for {width}x{height} uint16 raw frame, got {len(raw_bytes)}")
    if matrix_height <= 0 or matrix_height + 2 > height:
        raise ValueError(f"matrix_height must leave two addline rows within {height}, got {matrix_height}")
    full_frame = np.frombuffer(raw_bytes, dtype="<u2").reshape(height, width)
    raw_matrix = full_frame[:matrix_height, :].copy()
    addline_tag1 = full_frame[matrix_height : matrix_height + 2, :].astype("<u2", copy=False).tobytes()
    return Mini2RawFrameParts(raw_matrix=raw_matrix, addline_tag1=addline_tag1, full_frame_u16=full_frame.copy())


@dataclass(frozen=True)
class RawAffineCelsiusConverter:
    """Session calibration: ``temperature_c = raw * slope + intercept``."""

    slope_c_per_raw: float
    intercept_c: float
    calibration_source: str = "manual_affine_calibration"
    model_name: str = "raw_affine_celsius"
    calibrated: bool = True

    def convert(self, raw_matrix: np.ndarray) -> np.ndarray:
        _validate_raw_matrix(raw_matrix)
        return raw_matrix.astype(np.float64) * self.slope_c_per_raw + self.intercept_c

    @classmethod
    def from_json(cls, path: str | Path) -> "RawAffineCelsiusConverter":
        source = Path(path)
        payload = json.loads(source.read_text(encoding="utf-8"))
        try:
            slope = float(payload["slope_c_per_raw"])
            intercept = float(payload["intercept_c"])
        except KeyError as exc:
            raise ValueError(f"{source} is missing affine calibration key {exc.args[0]!r}") from exc
        return cls(slope_c_per_raw=slope, intercept_c=intercept, calibration_source=str(source))


@dataclass(frozen=True)
class RawLookupCelsiusConverter:
    """Lookup/piecewise converter derived from a calibrated raw/Celsius table."""

    raw_values: np.ndarray
    celsius_values: np.ndarray
    calibration_source: str = "raw_to_celsius_lookup"
    interpolate: bool = True
    model_name: str = "raw_lookup_celsius"
    calibrated: bool = True

    def __post_init__(self) -> None:
        raw = np.asarray(self.raw_values, dtype=np.uint16)
        celsius = np.asarray(self.celsius_values, dtype=np.float64)
        if raw.ndim != 1 or celsius.ndim != 1 or raw.size != celsius.size or raw.size == 0:
            raise ValueError("lookup raw and Celsius arrays must be non-empty 1D arrays of equal length")
        order = np.argsort(raw.astype(np.uint32), kind="stable")
        object.__setattr__(self, "raw_values", raw[order])
        object.__setattr__(self, "celsius_values", celsius[order])

    def convert(self, raw_matrix: np.ndarray) -> np.ndarray:
        _validate_raw_matrix(raw_matrix)
        raw_uint = raw_matrix.astype(np.uint16, copy=False)
        raw_float = raw_uint.astype(np.float64)
        low = float(self.raw_values[0])
        high = float(self.raw_values[-1])
        raw_min = float(raw_float.min())
        raw_max = float(raw_float.max())
        if raw_min < low or raw_max > high:
            raise ThermalConversionUnavailable(
                f"raw values {raw_min:g}..{raw_max:g} outside lookup range {low:g}..{high:g}; "
                "refusing to extrapolate Celsius values"
            )
        if not self.interpolate:
            flat_raw = raw_uint.ravel()
            positions = np.searchsorted(self.raw_values, flat_raw)
            in_bounds = positions < self.raw_values.size
            valid = np.zeros(flat_raw.shape, dtype=bool)
            valid[in_bounds] = self.raw_values[positions[in_bounds]] == flat_raw[in_bounds]
            if not bool(np.all(valid)):
                missing = int(flat_raw[int(np.where(~valid)[0][0])])
                raise ThermalConversionUnavailable(
                    f"raw value {missing} is not present in exact lookup table; "
                    "enable interpolation or provide a denser calibration table"
                )
            return self.celsius_values[positions].reshape(raw_matrix.shape)
        converted = np.interp(raw_float.ravel(), self.raw_values.astype(np.float64), self.celsius_values)
        return converted.reshape(raw_matrix.shape)

    @classmethod
    def from_csv(cls, path: str | Path, *, interpolate: bool = True) -> "RawLookupCelsiusConverter":
        source = Path(path)
        raw_values: list[int] = []
        celsius_values: list[float] = []
        with source.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or "raw_u16" not in reader.fieldnames:
                raise ValueError(f"{source} must have a raw_u16 column")
            celsius_column = _find_celsius_column(reader.fieldnames)
            for row in reader:
                raw_values.append(int(float(row["raw_u16"])))
                celsius_values.append(float(row[celsius_column]))
        return cls(
            raw_values=np.array(raw_values, dtype=np.uint16),
            celsius_values=np.array(celsius_values, dtype=np.float64),
            calibration_source=str(source),
            interpolate=interpolate,
        )


def _find_celsius_column(fieldnames: list[str]) -> str:
    for name in fieldnames:
        lowered = name.lower()
        if name != "raw_u16" and ("celsius" in lowered or "temp" in lowered):
            return name
    raise ValueError("lookup CSV must have a Celsius/temperature column")


def load_raw_to_celsius_converter(config: dict[str, object]) -> RawToCelsiusConverter:
    """Load a raw->Celsius converter from a small config mapping.

    Supported configs::

        {"type": "affine", "path": "data/mini2_roi_calibration/roi_formula.json"}
        {"type": "affine", "slope_c_per_raw": 0.025, "intercept_c": -105.25}
        {"type": "lookup", "path": "data/.../raw_to_celsius_lookup.csv"}
        {"type": "official_mtlib", "metadata_jpeg": "data/fixtures/mini2/IR_00001.jpeg"}
        {"type": "official_worker", "command": "py.exe -3 tools/mini2_official_mtlib_worker_win.py ..."}
    """

    converter_type = str(config.get("type", "")).strip().lower()
    if not converter_type:
        raise ThermalConversionUnavailable("raw_to_celsius converter config must include type")
    if converter_type == "affine":
        path = config.get("path")
        if path:
            return RawAffineCelsiusConverter.from_json(str(path))
        try:
            return RawAffineCelsiusConverter(
                slope_c_per_raw=float(config["slope_c_per_raw"]),
                intercept_c=float(config["intercept_c"]),
                calibration_source="inline_affine_config",
            )
        except KeyError as exc:
            raise ValueError(f"inline affine config missing {exc.args[0]!r}") from exc
    if converter_type == "lookup":
        path = config.get("path")
        if not path:
            raise ValueError("lookup converter config requires path")
        return RawLookupCelsiusConverter.from_csv(str(path), interpolate=bool(config.get("interpolate", True)))
    if converter_type in {"official_mtlib", "hikmicro_official_mtlib"}:
        from .official_hikmicro import DLL_DIR_DEFAULT, OfficialMtlibConverter

        metadata_jpeg = config.get("metadata_jpeg") or config.get("jpeg") or config.get("path")
        if not metadata_jpeg:
            raise ValueError("official_mtlib converter config requires metadata_jpeg")
        dll_dir = str(config.get("dll_dir") or DLL_DIR_DEFAULT)
        batch_size = int(config.get("batch_size", 32))
        return OfficialMtlibConverter.from_jpeg(str(metadata_jpeg), dll_dir=dll_dir, batch_size=batch_size)
    if converter_type in {"official_worker", "official_mtlib_worker", "hikmicro_official_worker"}:
        from .official_hikmicro import OfficialMtlibWorkerConverter

        command_value = config.get("command")
        if not command_value:
            raise ValueError("official_worker converter config requires command")
        command = _split_worker_command(str(command_value)) if isinstance(command_value, str) else [str(part) for part in command_value]  # type: ignore[iterable]
        calibration_source = str(config.get("calibration_source") or config.get("metadata_jpeg") or "official_mtlib_worker")
        return OfficialMtlibWorkerConverter(command, calibration_source=calibration_source)
    raise ValueError(f"unsupported raw_to_celsius converter type {converter_type!r}")


def _split_worker_command(command: str) -> list[str]:
    """Split a Windows worker command without eating backslashes.

    POSIX shlex treats backslashes in UNC paths and ``C:\\Program Files`` as
    escapes. The worker command is normally a Windows command launched through
    WSL interop, so keep Windows backslashes literal and strip quote wrappers.
    """

    parts = shlex.split(command, posix=False)
    cleaned: list[str] = []
    for part in parts:
        if len(part) >= 2 and part[0] == part[-1] and part[0] in {"'", '"'}:
            cleaned.append(part[1:-1])
        else:
            cleaned.append(part)
    return cleaned


class Mini2FfmpegRawFrameReader:
    """Read 25fps Mini2 raw UVC frames from ffmpeg stdout."""

    def __init__(
        self,
        *,
        device: str = "/dev/video0",
        frame_rate_hz: float = MINI2_FRAME_RATE_HZ,
        input_format: str = MINI2_INPUT_FORMAT,
        width: int = MINI2_UVC_WIDTH,
        height: int = MINI2_UVC_HEIGHT,
        popen_factory=subprocess.Popen,
    ) -> None:
        self.device = device
        self.frame_rate_hz = float(frame_rate_hz)
        self.input_format = input_format
        self.width = int(width)
        self.height = int(height)
        self._popen_factory = popen_factory
        self._process: subprocess.Popen[bytes] | None = None

    def command(self) -> list[str]:
        return [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "v4l2",
            "-framerate",
            _format_rate(self.frame_rate_hz),
            "-input_format",
            self.input_format,
            "-video_size",
            f"{self.width}x{self.height}",
            "-i",
            self.device,
            "-f",
            "rawvideo",
            "pipe:1",
        ]

    def start(self) -> None:
        if self._process is not None:
            return
        self._process = self._popen_factory(self.command(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def read_frame_bytes(self) -> bytes:
        self.start()
        assert self._process is not None
        if self._process.stdout is None:
            raise RuntimeError("ffmpeg stdout pipe is unavailable")
        frame_bytes = _read_exact(self._process.stdout, expected_raw_frame_bytes(self.width, self.height))
        if len(frame_bytes) != expected_raw_frame_bytes(self.width, self.height):
            raise EOFError("ffmpeg ended before a complete Mini2 raw frame was read")
        return frame_bytes

    def read_raw_matrix(self) -> np.ndarray:
        return extract_mini2_raw_matrix(self.read_frame_bytes(), width=self.width, height=self.height)

    def read_frame_parts(self) -> Mini2RawFrameParts:
        return extract_mini2_frame_parts(self.read_frame_bytes(), width=self.width, height=self.height)

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        for stream_name in ("stdout", "stderr"):
            stream = getattr(process, stream_name, None)
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass

    def __enter__(self) -> "Mini2FfmpegRawFrameReader":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.close()


@dataclass(frozen=True)
class Mini2TemperatureFrame:
    """One full Mini2 frame after raw extraction and Celsius conversion."""

    frame_id: int
    timestamp_s: float
    raw_matrix: np.ndarray
    temperature_matrix_c: np.ndarray
    converter_name: str
    calibration_source: str
    frame_rate_hz: float


def build_temperature_frame(
    *,
    raw_matrix: np.ndarray,
    converter: RawToCelsiusConverter | None,
    frame_id: int,
    addline_tag1: bytes | None = None,
    timestamp_s: float | None = None,
    frame_rate_hz: float = MINI2_FRAME_RATE_HZ,
) -> Mini2TemperatureFrame:
    if converter is None:
        raise ThermalConversionUnavailable("Mini2 raw frames require an explicit raw->Celsius converter")
    temperature_matrix_c = _convert_raw_matrix(converter, raw_matrix, addline_tag1)
    if temperature_matrix_c.shape != raw_matrix.shape:
        raise ValueError("converter returned a matrix with a different shape")
    return Mini2TemperatureFrame(
        frame_id=frame_id,
        timestamp_s=time.monotonic() if timestamp_s is None else float(timestamp_s),
        raw_matrix=raw_matrix,
        temperature_matrix_c=temperature_matrix_c.astype(np.float64, copy=False),
        converter_name=converter.model_name,
        calibration_source=converter.calibration_source,
        frame_rate_hz=float(frame_rate_hz),
    )


def _convert_raw_matrix(
    converter: RawToCelsiusConverter,
    raw_matrix: np.ndarray,
    addline_tag1: bytes | None,
) -> np.ndarray:
    if addline_tag1 is not None and hasattr(converter, "convert_with_addline"):
        return converter.convert_with_addline(raw_matrix, addline_tag1)  # type: ignore[attr-defined]
    return converter.convert(raw_matrix)


def extract_temperature_features(
    matrix_c: np.ndarray,
    roi: Roi,
    *,
    raw_matrix: np.ndarray | None = None,
    previous: dict[str, object] | None = None,
    source_name: str = "mini2_uvc_raw_celsius",
    converter_name: str = "unknown",
    calibration_source: str = "unknown",
    frame_rate_hz: float = MINI2_FRAME_RATE_HZ,
) -> dict[str, object]:
    """Return scalar ROI and whole-matrix features without serializing the matrix."""

    _validate_temperature_matrix(matrix_c)
    _validate_matrix_roi(matrix_c, roi)
    region = matrix_c[roi.y : roi.y + roi.height, roi.x : roi.x + roi.width]
    roi_coords_yx = _rect_coords_yx(roi)
    matrix_min_yx = np.unravel_index(int(np.argmin(matrix_c)), matrix_c.shape)
    matrix_max_yx = np.unravel_index(int(np.argmax(matrix_c)), matrix_c.shape)
    roi_avg = round(float(np.mean(region)), 6)
    previous_roi_avg = _float_or_none((previous or {}).get("thermal_roi_avg"))
    roi_delta = 0.0 if previous_roi_avg is None else roi_avg - previous_roi_avg

    features: dict[str, object] = {
        "thermal_source": source_name,
        "thermal_calibrated": True,
        "source_quality": "mini2_uvc_raw_calibrated_temperature_matrix",
        "thermal_conversion_model": converter_name,
        "thermal_conversion_calibration_source": calibration_source,
        "thermal_frame_rate_hz": float(frame_rate_hz),
        "thermal_matrix_shape": f"{matrix_c.shape[0]}x{matrix_c.shape[1]}",
        "thermal_roi_avg": roi_avg,
        "thermal_roi_max": round(float(np.max(region)), 6),
        "thermal_roi_min": round(float(np.min(region)), 6),
        "thermal_roi_std": round(float(np.std(region)), 12),
        "thermal_roi_delta": round(float(roi_delta), 6),
        "thermal_matrix_avg": round(float(np.mean(matrix_c)), 6),
        "thermal_matrix_max": round(float(np.max(matrix_c)), 6),
        "thermal_matrix_min": round(float(np.min(matrix_c)), 6),
        "thermal_matrix_std": round(float(np.std(matrix_c)), 12),
        "thermal_matrix_min_x": int(matrix_min_yx[1]),
        "thermal_matrix_min_y": int(matrix_min_yx[0]),
        "thermal_matrix_max_x": int(matrix_max_yx[1]),
        "thermal_matrix_max_y": int(matrix_max_yx[0]),
        "warnings": "",
    }
    features.update(_distribution_features("thermal_roi", region, coords_yx=roi_coords_yx))
    features.update(_distribution_features("thermal_matrix", matrix_c))
    if raw_matrix is not None:
        _validate_raw_matrix(raw_matrix)
        raw_region = raw_matrix[roi.y : roi.y + roi.height, roi.x : roi.x + roi.width]
        features.update(
            {
                "thermal_raw_roi_avg": round(float(np.mean(raw_region)), 6),
                "thermal_raw_roi_max": int(np.max(raw_region)),
                "thermal_raw_roi_min": int(np.min(raw_region)),
                "thermal_raw_roi_std": round(float(np.std(raw_region)), 6),
                "thermal_raw_min": int(np.min(raw_matrix)),
                "thermal_raw_max": int(np.max(raw_matrix)),
                "thermal_raw_mean": round(float(np.mean(raw_matrix)), 6),
                "thermal_raw_std": round(float(np.std(raw_matrix)), 6),
            }
        )
        features.update(_distribution_features("thermal_raw_roi", raw_region, coords_yx=roi_coords_yx))
        features.update(_distribution_features("thermal_raw", raw_matrix.astype(np.float64)))
    return features


def _validate_raw_matrix(raw_matrix: np.ndarray) -> None:
    if raw_matrix.shape != MINI2_MATRIX_SHAPE:
        raise ValueError(f"Mini2 raw matrix must have shape {MINI2_MATRIX_SHAPE}, got {raw_matrix.shape}")
    if raw_matrix.dtype.kind not in {"u", "i"}:
        raise ValueError(f"Mini2 raw matrix must contain integer raw values, got {raw_matrix.dtype}")


def _validate_temperature_matrix(matrix_c: np.ndarray) -> None:
    if matrix_c.shape != MINI2_MATRIX_SHAPE:
        raise ValueError(f"Mini2 temperature matrix must have shape {MINI2_MATRIX_SHAPE}, got {matrix_c.shape}")
    if not np.issubdtype(matrix_c.dtype, np.number):
        raise ValueError("Mini2 temperature matrix must be numeric")


def _validate_matrix_roi(matrix: np.ndarray, roi: Roi) -> None:
    if roi.width <= 0 or roi.height <= 0:
        raise ValueError("ROI width and height must be positive")
    height, width = matrix.shape[:2]
    if roi.x < 0 or roi.y < 0 or roi.x + roi.width > width or roi.y + roi.height > height:
        raise ValueError(f"ROI {roi} is outside matrix shape {matrix.shape}")


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _round_float(value: object, digits: int = 6) -> float:
    return round(float(value), digits)


def _rect_coords_yx(roi: Roi) -> np.ndarray:
    yy, xx = np.indices((roi.height, roi.width), dtype=np.int64)
    yy += int(roi.y)
    xx += int(roi.x)
    return np.column_stack([yy.ravel(), xx.ravel()])


def _distribution_features(prefix: str, values: np.ndarray, *, coords_yx: np.ndarray | None = None) -> dict[str, object]:
    arr = np.asarray(values, dtype=np.float64).reshape(-1)
    if arr.size == 0:
        return {}
    p05, p25, p50, p75, p95 = np.percentile(arr, [5, 25, 50, 75, 95])
    avg = float(np.mean(arr))
    std = float(np.std(arr))
    features: dict[str, object] = {
        f"{prefix}_range": _round_float(np.max(arr) - np.min(arr)),
        f"{prefix}_iqr": _round_float(p75 - p25),
        f"{prefix}_p05": _round_float(p05),
        f"{prefix}_p25": _round_float(p25),
        f"{prefix}_p50": _round_float(p50),
        f"{prefix}_p75": _round_float(p75),
        f"{prefix}_p95": _round_float(p95),
        f"{prefix}_hot_fraction": 0.0 if std == 0.0 else _round_float(np.mean(arr > avg + std)),
        f"{prefix}_cold_fraction": 0.0 if std == 0.0 else _round_float(np.mean(arr < avg - std)),
    }
    if coords_yx is not None:
        coords = np.asarray(coords_yx, dtype=np.int64).reshape(-1, 2)
        if coords.shape[0] == arr.size:
            min_y, min_x = coords[int(np.argmin(arr))]
            max_y, max_x = coords[int(np.argmax(arr))]
            features.update(
                {
                    f"{prefix}_min_x": int(min_x),
                    f"{prefix}_min_y": int(min_y),
                    f"{prefix}_max_x": int(max_x),
                    f"{prefix}_max_y": int(max_y),
                }
            )
    return features


def _format_rate(rate: float) -> str:
    return str(int(rate)) if float(rate).is_integer() else f"{rate:g}"


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
