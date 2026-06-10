"""USB camera capture wrappers.

OpenCV is imported lazily so the analysis modules remain testable without
camera dependencies installed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CameraConfig:
    device_index: int
    width: int | None = None
    height: int | None = None
    backend: str | None = None
    name: str = "camera"


class UsbCamera:
    """Read RGB frames from an OpenCV-compatible USB/UVC camera."""

    def __init__(self, config: CameraConfig) -> None:
        self.config = config
        try:
            import cv2  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("opencv-python is required for USB camera capture") from exc
        self._cv2 = cv2
        backend_value = self._backend_value(cv2, config.backend)
        self._capture = (
            cv2.VideoCapture(config.device_index, backend_value)
            if backend_value is not None
            else cv2.VideoCapture(config.device_index)
        )
        if config.width:
            self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, config.width)
        if config.height:
            self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, config.height)
        if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
            self._capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self._capture.isOpened():
            raise RuntimeError(f"could not open {config.name} at device index {config.device_index}")

    def read_rgb(self) -> np.ndarray:
        ok, frame_bgr = self._capture.read()
        if not ok or frame_bgr is None:
            raise RuntimeError(f"failed to read frame from {self.config.name}")
        return self._cv2.cvtColor(frame_bgr, self._cv2.COLOR_BGR2RGB)

    def release(self) -> None:
        self._capture.release()

    @staticmethod
    def _backend_value(cv2, backend: str | None) -> int | None:  # type: ignore[no-untyped-def]
        if backend in (None, "", "auto", "any"):
            return None
        normalized = backend.upper()
        mapping = {
            "DSHOW": "CAP_DSHOW",
            "DIRECTSHOW": "CAP_DSHOW",
            "MSMF": "CAP_MSMF",
            "MEDIAFOUNDATION": "CAP_MSMF",
        }
        attribute = mapping.get(normalized)
        if attribute is None or not hasattr(cv2, attribute):
            raise ValueError(f"unsupported OpenCV camera backend: {backend}")
        return int(getattr(cv2, attribute))
