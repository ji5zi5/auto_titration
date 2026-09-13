"""Color feature extraction for visible and thermal-palette camera frames."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Mapping

import numpy as np

try:  # Camera deployments already depend on OpenCV; import before recording starts.
    import cv2 as _cv2  # type: ignore
except ImportError:  # pragma: no cover - exercised only in dependency-free installs.
    _cv2 = None


@dataclass(frozen=True)
class Roi:
    """Rectangular region of interest in pixel coordinates."""

    x: int
    y: int
    width: int
    height: int

    def validate_for(self, frame: np.ndarray) -> None:
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("frame must have shape (height, width, 3)")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("ROI width and height must be positive")
        frame_h, frame_w = frame.shape[:2]
        if self.x < 0 or self.y < 0 or self.x + self.width > frame_w or self.y + self.height > frame_h:
            raise ValueError("ROI must be fully inside the frame")

    def crop(self, frame: np.ndarray) -> np.ndarray:
        self.validate_for(frame)
        return frame[self.y : self.y + self.height, self.x : self.x + self.width]


def rgb_to_hsv(rgb: np.ndarray) -> np.ndarray:
    """Convert RGB uint8/float image to HSV with H degrees and S/V in 0..1."""

    # OpenCV performs the same RGB->HSV transform in compiled code and is
    # already required by the camera collector.  Returning float64 keeps the
    # downstream mean/rounding behavior stable.  The NumPy implementation below
    # remains the dependency-free fallback used in minimal test environments.
    try:
        normalized = np.ascontiguousarray(np.asarray(rgb), dtype=np.float32) / np.float32(255.0)
        if _cv2 is not None and normalized.ndim == 3 and normalized.shape[-1] == 3 and normalized.size:
            return _cv2.cvtColor(normalized, _cv2.COLOR_RGB2HSV).astype(np.float64)
    except (AttributeError, TypeError, ValueError):
        pass

    arr = rgb.astype(np.float64) / 255.0
    r = arr[..., 0]
    g = arr[..., 1]
    b = arr[..., 2]

    maxc = np.max(arr, axis=-1)
    minc = np.min(arr, axis=-1)
    delta = maxc - minc

    hue = np.zeros_like(maxc)
    nonzero = delta != 0

    red_max = (maxc == r) & nonzero
    green_max = (maxc == g) & nonzero
    blue_max = (maxc == b) & nonzero

    hue[red_max] = (60.0 * ((g[red_max] - b[red_max]) / delta[red_max])) % 360.0
    hue[green_max] = 60.0 * ((b[green_max] - r[green_max]) / delta[green_max] + 2.0)
    hue[blue_max] = 60.0 * ((r[blue_max] - g[blue_max]) / delta[blue_max] + 4.0)

    saturation = np.zeros_like(maxc)
    has_value = maxc != 0
    saturation[has_value] = delta[has_value] / maxc[has_value]

    return np.stack([hue, saturation, maxc], axis=-1)


class ColorFeatureExtractor:
    """Extract mean RGB/HSV and frame-to-frame color change from an ROI."""

    def extract(
        self,
        frame_rgb: np.ndarray,
        roi: Roi,
        previous: Mapping[str, float] | None = None,
    ) -> dict[str, float]:
        cropped = roi.crop(frame_rgb)
        rgb_mean = np.mean(cropped, axis=(0, 1), dtype=np.float64)
        hsv_mean = np.mean(rgb_to_hsv(cropped), axis=(0, 1), dtype=np.float64)

        features = {
            "R_mean": round(float(rgb_mean[0]), 6),
            "G_mean": round(float(rgb_mean[1]), 6),
            "B_mean": round(float(rgb_mean[2]), 6),
            "H_mean": round(float(hsv_mean[0]), 6),
            "S_mean": round(float(hsv_mean[1]), 6),
            "V_mean": round(float(hsv_mean[2]), 6),
        }
        features["color_delta"] = round(self._color_delta(features, previous), 6)
        features.update(self._hsv_delta(features, previous))
        return features

    @staticmethod
    def _color_delta(current: Mapping[str, float], previous: Mapping[str, float] | None) -> float:
        if not previous:
            return 0.0
        return sqrt(
            (current["R_mean"] - float(previous["R_mean"])) ** 2
            + (current["G_mean"] - float(previous["G_mean"])) ** 2
            + (current["B_mean"] - float(previous["B_mean"])) ** 2
        )

    @staticmethod
    def _hue_delta_deg(current_h: float, previous_h: float) -> float:
        """Smallest circular hue distance in degrees."""

        diff = abs((float(current_h) - float(previous_h)) % 360.0)
        return min(diff, 360.0 - diff)

    @staticmethod
    def _hsv_delta(current: Mapping[str, float], previous: Mapping[str, float] | None) -> dict[str, float]:
        if not previous:
            return {"H_delta": 0.0, "S_delta": 0.0, "V_delta": 0.0, "HSV_delta": 0.0}
        try:
            h_delta = ColorFeatureExtractor._hue_delta_deg(current["H_mean"], float(previous["H_mean"]))
            s_delta = abs(float(current["S_mean"]) - float(previous["S_mean"]))
            v_delta = abs(float(current["V_mean"]) - float(previous["V_mean"]))
        except (KeyError, TypeError, ValueError):
            return {"H_delta": 0.0, "S_delta": 0.0, "V_delta": 0.0, "HSV_delta": 0.0}
        hsv_delta = sqrt((h_delta / 180.0) ** 2 + s_delta**2 + v_delta**2)
        return {
            "H_delta": round(float(h_delta), 6),
            "S_delta": round(float(s_delta), 6),
            "V_delta": round(float(v_delta), 6),
            "HSV_delta": round(float(hsv_delta), 6),
        }


def prefix_features(features: Mapping[str, float], prefix: str) -> dict[str, float]:
    """Prefix base color feature names for CSV columns."""

    return {f"{prefix}_{name}": value for name, value in features.items()}
