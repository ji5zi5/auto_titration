"""Thermal source providers for live/replay equivalence-point analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from .color_analysis import Roi
from .mini2_live import (
    MINI2_FRAME_RATE_HZ,
    Mini2FfmpegRawFrameReader,
    RawToCelsiusConverter,
    build_temperature_frame,
    extract_temperature_features,
)
from .thermal_camera import HikmicroTemperatureMatrix, is_celsius_unit


@dataclass(frozen=True)
class ThermalFramePacket:
    """One thermal-provider read result.

    `temperature_matrix_c` is available only for calibrated or replayed Celsius
    data. Display frames may be palette images and must not be treated as true
    temperature matrices.
    """

    source_name: str
    display_frame: np.ndarray | None = None
    raw_matrix: np.ndarray | None = None
    temperature_matrix_c: np.ndarray | None = None
    calibrated_temperature: bool = False
    frame_id: int | None = None
    timestamp_s: float | None = None
    warnings: tuple[str, ...] = ()


class NullThermalProvider:
    """Provider used when Mini2/thermal data is unavailable."""

    def __init__(self, reason: str = "thermal source unavailable") -> None:
        self.reason = reason

    def read(self) -> ThermalFramePacket:
        return ThermalFramePacket(
            source_name="thermal_unavailable",
            calibrated_temperature=False,
            warnings=(self.reason,),
        )

    def extract_roi_features(self, roi: Roi) -> dict[str, object]:  # noqa: ARG002 - ROI kept for interface consistency.
        return {
            "thermal_source": "thermal_unavailable",
            "thermal_calibrated": False,
            "warnings": self.reason,
        }


class MatrixReplayThermalProvider:
    """Replay a calibrated HIKMICRO temperature matrix fixture/export."""

    def __init__(self, matrix: HikmicroTemperatureMatrix, source_name: str = "hikmicro_matrix_replay") -> None:
        self.matrix = matrix
        self.source_name = source_name

    def read(self) -> ThermalFramePacket:
        calibrated = is_celsius_unit(self.matrix.unit)
        warnings = () if calibrated else (f"temperature matrix unit {self.matrix.unit!r} is not verified Celsius",)
        return ThermalFramePacket(
            source_name=self.source_name,
            temperature_matrix_c=self.matrix.values if calibrated else None,
            calibrated_temperature=calibrated,
            warnings=warnings,
        )

    def extract_roi_features(self, roi: Roi) -> dict[str, object]:
        features: dict[str, object] = dict(self.matrix.extract_roi(roi))
        features["thermal_source"] = self.source_name
        features["thermal_calibrated"] = is_celsius_unit(self.matrix.unit)
        return features


class Mini2RawTemperatureProvider:
    """Live Mini2 UVC raw-frame provider that returns calibrated Celsius matrices."""

    def __init__(
        self,
        *,
        converter: RawToCelsiusConverter,
        reader: Mini2FfmpegRawFrameReader | None = None,
        source_name: str = "mini2_uvc_raw_celsius",
        frame_rate_hz: float = MINI2_FRAME_RATE_HZ,
    ) -> None:
        self.converter = converter
        self.reader = reader or Mini2FfmpegRawFrameReader(frame_rate_hz=frame_rate_hz)
        self.source_name = source_name
        self.frame_rate_hz = float(frame_rate_hz)
        self._frame_id = 0
        self._latest_packet: ThermalFramePacket | None = None

    def read(self) -> ThermalFramePacket:
        addline_tag1 = None
        if hasattr(self.reader, "read_frame_parts"):
            parts = self.reader.read_frame_parts()
            raw_matrix = parts.raw_matrix
            addline_tag1 = parts.addline_tag1
        else:
            raw_matrix = self.reader.read_raw_matrix()
        frame = build_temperature_frame(
            raw_matrix=raw_matrix,
            converter=self.converter,
            frame_id=self._frame_id,
            addline_tag1=addline_tag1,
            frame_rate_hz=self.frame_rate_hz,
        )
        self._frame_id += 1
        packet = ThermalFramePacket(
            source_name=self.source_name,
            raw_matrix=frame.raw_matrix,
            temperature_matrix_c=frame.temperature_matrix_c,
            calibrated_temperature=True,
            frame_id=frame.frame_id,
            timestamp_s=frame.timestamp_s,
            warnings=(),
        )
        self._latest_packet = packet
        return packet

    def extract_roi_features(
        self,
        roi: Roi,
        *,
        previous: dict[str, object] | None = None,
        packet: ThermalFramePacket | None = None,
    ) -> dict[str, object]:
        source = packet or self._latest_packet or self.read()
        if source.temperature_matrix_c is None:
            raise RuntimeError("Mini2 raw provider has no Celsius matrix for ROI extraction")
        return extract_temperature_features(
            source.temperature_matrix_c,
            roi,
            raw_matrix=source.raw_matrix,
            previous=previous,
            source_name=self.source_name,
            converter_name=self.converter.model_name,
            calibration_source=self.converter.calibration_source,
            frame_rate_hz=self.frame_rate_hz,
        )

    def close(self) -> None:
        self.reader.close()


class PaletteFrameProvider:
    """Return a display/palette frame that is explicitly not calibrated Celsius."""

    def __init__(self, frame_reader: Callable[[], np.ndarray], source_name: str = "usb_palette_uncalibrated") -> None:
        self.frame_reader = frame_reader
        self.source_name = source_name

    def read(self) -> ThermalFramePacket:
        return ThermalFramePacket(
            source_name=self.source_name,
            display_frame=self.frame_reader(),
            calibrated_temperature=False,
            warnings=("palette frame is not calibrated Celsius temperature",),
        )
