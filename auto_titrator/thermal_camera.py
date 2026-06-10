"""Thermal camera helpers.

The first implementation assumes HIKMICRO Mini2 V2 appears as a USB/UVC video
source that shows a thermal palette image. These are palette-color features,
not calibrated temperature values.

HIKMICRO Analyzer/App CSV exports are different: they can contain an already
calibrated Celsius temperature matrix. Those files should be parsed directly
instead of reverse-engineering the palette colors.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np

from .color_analysis import ColorFeatureExtractor, Roi, prefix_features


CELSIUS_UNITS = {"섭씨", "°C", "℃", "C", "c", "Celsius", "celsius", "degC", "deg_c"}


def is_celsius_unit(unit: str | None) -> bool:
    """Return True only for unit labels verified as Celsius."""

    return (unit or "").strip() in CELSIUS_UNITS


class ThermalPaletteAnalyzer:
    """Extract thermal-palette color features from a USB thermal video frame."""

    def __init__(self, source_name: str = "usb_palette_uncalibrated") -> None:
        self.source_name = source_name
        self._extractor = ColorFeatureExtractor()

    def extract(
        self,
        frame_rgb: np.ndarray,
        roi: Roi,
        previous: Mapping[str, float] | None = None,
    ) -> dict[str, float | bool | str]:
        base_previous = None
        if previous:
            base_previous = {
                "R_mean": previous.get("thermal_R_mean", 0.0),
                "G_mean": previous.get("thermal_G_mean", 0.0),
                "B_mean": previous.get("thermal_B_mean", 0.0),
                "H_mean": previous.get("thermal_H_mean", 0.0),
                "S_mean": previous.get("thermal_S_mean", 0.0),
                "V_mean": previous.get("thermal_V_mean", 0.0),
            }
        features: dict[str, float | bool | str] = dict(
            prefix_features(self._extractor.extract(frame_rgb, roi, base_previous), "thermal")
        )
        features["thermal_source"] = self.source_name
        features["thermal_calibrated"] = False
        features["source_quality"] = "palette_uncalibrated"
        features["warnings"] = "palette frame is not calibrated Celsius temperature"
        return features


@dataclass(frozen=True)
class HikmicroTemperatureMatrix:
    """Calibrated temperature matrix exported by HIKMICRO Analyzer/App."""

    values: np.ndarray
    unit: str
    metadata: Mapping[str, float | str]
    source_path: str

    def extract_roi(self, roi: Roi) -> dict[str, float | bool | str]:
        if roi.x < 0 or roi.y < 0 or roi.x + roi.width > self.values.shape[1] or roi.y + roi.height > self.values.shape[0]:
            raise ValueError(f"ROI {roi} is outside temperature matrix shape {self.values.shape}")
        calibrated = is_celsius_unit(self.unit)
        if not calibrated:
            return {
                "thermal_source": "hikmicro_export_csv",
                "thermal_calibrated": False,
                "source_quality": "non_celsius_temperature_matrix",
                "warnings": f"temperature matrix unit {self.unit!r} is not verified Celsius",
            }

        region = self.values[roi.y : roi.y + roi.height, roi.x : roi.x + roi.width]
        features: dict[str, float | bool | str] = {
            "thermal_source": "hikmicro_export_csv",
            "thermal_roi_avg": round(float(np.mean(region)), 6),
            "thermal_roi_max": round(float(np.max(region)), 6),
            "thermal_roi_min": round(float(np.min(region)), 6),
            "thermal_roi_std": round(float(np.std(region)), 12),
            "thermal_calibrated": True,
            "source_quality": "calibrated_temperature_matrix",
        }
        return features


def _read_hikmicro_csv_rows(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp949", "euc-kr", "latin1"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        rows = list(csv.reader(text.splitlines()))
        if any(row and row[0].strip() == "축 X/Y" for row in rows):
            return rows
    raise ValueError(f"{path} is not a recognizable HIKMICRO temperature matrix CSV")


def _cell_float(value: str) -> float:
    return float(value.strip())


def load_hikmicro_temperature_csv(path: str | Path) -> HikmicroTemperatureMatrix:
    """Load a HIKMICRO exported temperature matrix CSV.

    The Korean Analyzer export observed in this repo is CP949 encoded and has
    metadata rows followed by `축 X/Y,0,1,...` and then one row per Y pixel.
    Matrix values are already Celsius when `단위,섭씨` is present.
    """

    csv_path = Path(path)
    rows = _read_hikmicro_csv_rows(csv_path)
    unit = ""
    metadata: dict[str, float | str] = {}
    axis_index = None

    for index, row in enumerate(rows):
        if not row:
            continue
        first = row[0].strip()
        if first == "축 X/Y":
            axis_index = index
            break
        if first == "단위" and len(row) > 1:
            unit = row[1].strip()
        if "평균:" in row:
            pos = row.index("평균:")
            if pos + 1 < len(row) and row[pos + 1].strip():
                metadata["평균"] = _cell_float(row[pos + 1])
        if "분:" in row:
            pos = row.index("분:")
            if pos + 1 < len(row) and row[pos + 1].strip():
                metadata["분"] = _cell_float(row[pos + 1])
        if "최대:" in row:
            pos = row.index("최대:")
            if pos + 1 < len(row) and row[pos + 1].strip():
                metadata["최대"] = _cell_float(row[pos + 1])

    if axis_index is None:
        raise ValueError(f"{csv_path} has no HIKMICRO axis row")

    matrix_rows: list[list[float]] = []
    expected_width = None
    for row in rows[axis_index + 1 :]:
        if not row or not row[0].strip():
            continue
        try:
            int(float(row[0]))
            values = [_cell_float(cell) for cell in row[1:] if cell.strip()]
        except ValueError:
            continue
        if expected_width is None:
            expected_width = len(values)
        if len(values) != expected_width:
            raise ValueError(f"inconsistent matrix row width in {csv_path}: expected {expected_width}, got {len(values)}")
        matrix_rows.append(values)

    if not matrix_rows:
        raise ValueError(f"{csv_path} has no temperature matrix rows")

    values = np.array(matrix_rows, dtype=float)
    return HikmicroTemperatureMatrix(values=values, unit=unit, metadata=metadata, source_path=str(csv_path))
