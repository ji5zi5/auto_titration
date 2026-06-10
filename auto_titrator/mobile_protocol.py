"""Mobile feature-frame protocol for Android sensor companion mode.

The Android app is the sensor node in mobile mode.  This module keeps that
boundary testable without Android hardware: validate one phone-produced feature
frame, map it into the existing CSV row shape, estimate phone/server clock
alignment, and generate deterministic fake 25 Hz payloads for load tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
from typing import Any, Iterable, Mapping

MOBILE_FRAME_SCHEMA_VERSION = "mobile_feature_frame.v1"

_VISIBLE_FEATURE_MAP = {
    "R_mean": "visible_R_mean",
    "G_mean": "visible_G_mean",
    "B_mean": "visible_B_mean",
    "H_mean": "visible_H_mean",
    "S_mean": "visible_S_mean",
    "V_mean": "visible_V_mean",
    "H_delta": "visible_H_delta",
    "S_delta": "visible_S_delta",
    "V_delta": "visible_V_delta",
    "HSV_delta": "visible_HSV_delta",
    "color_delta": "visible_color_delta",
}

_ROI_SUMMARY_MAP = {
    "avg": "avg",
    "mean": "avg",
    "min": "min",
    "max": "max",
    "std": "std",
    "range": "range",
    "iqr": "iqr",
    "p05": "p05",
    "p25": "p25",
    "p50": "p50",
    "median": "p50",
    "p75": "p75",
    "p95": "p95",
    "hot_fraction": "hot_fraction",
    "cold_fraction": "cold_fraction",
    "delta": "delta",
}

_MATRIX_SUMMARY_MAP = {
    "avg": "avg",
    "mean": "mean",
    "min": "min",
    "max": "max",
    "std": "std",
    "range": "range",
    "iqr": "iqr",
    "p05": "p05",
    "p25": "p25",
    "p50": "p50",
    "median": "p50",
    "p75": "p75",
    "p95": "p95",
}


class MobileProtocolError(ValueError):
    """Raised when a mobile feature payload is malformed or unsafe."""


@dataclass(frozen=True)
class ClockSyncResult:
    offset_ms: float
    jitter_ms: float
    rtt_ms: float
    sample_count: int
    quality: str


@dataclass(frozen=True)
class FrameCountAssessment:
    ok: bool
    expected_count: int
    minimum_count: int
    actual_count: int
    fraction: float


def validate_mobile_feature_frame(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a normalized mobile frame payload or raise ``MobileProtocolError``.

    Validation is intentionally strict at the protocol boundary so raw thermal
    values cannot accidentally become calibrated Celsius values downstream.
    """

    if not isinstance(payload, Mapping):
        raise MobileProtocolError("mobile payload must be a JSON object")
    normalized = dict(payload)
    schema_version = str(normalized.get("schema_version") or "").strip()
    if schema_version != MOBILE_FRAME_SCHEMA_VERSION:
        raise MobileProtocolError(f"schema_version must be {MOBILE_FRAME_SCHEMA_VERSION}")
    source_platform = str(normalized.get("source_platform") or "").strip().lower()
    if source_platform not in {"android"}:
        raise MobileProtocolError("source_platform must be android")
    normalized["source_platform"] = source_platform
    for key in ("device_id", "run_id"):
        value = str(normalized.get(key) or "").strip()
        if not value:
            raise MobileProtocolError(f"{key} is required")
        normalized[key] = value[:160]
    normalized["frame_id"] = _required_int(normalized, "frame_id", minimum=0)
    normalized["phone_monotonic_ns"] = _required_int(normalized, "phone_monotonic_ns", minimum=0)
    normalized["phone_epoch_s"] = _required_float(normalized, "phone_epoch_s")
    if "clock_offset_ms" in normalized:
        normalized["clock_offset_ms"] = _required_float(normalized, "clock_offset_ms")
    if "clock_jitter_ms" in normalized:
        normalized["clock_jitter_ms"] = _required_float(normalized, "clock_jitter_ms", minimum=0.0)

    if "visible" in normalized and normalized["visible"] is not None:
        normalized["visible"] = _validate_sensor_block(normalized["visible"], sensor="visible")
    if "thermal" in normalized and normalized["thermal"] is not None:
        normalized["thermal"] = _validate_sensor_block(normalized["thermal"], sensor="thermal")
    if "visible" not in normalized and "thermal" not in normalized:
        raise MobileProtocolError("at least one visible or thermal block is required")
    return normalized


def mobile_payload_to_csv_row(payload: Mapping[str, Any], *, server_received_epoch_s: float | None = None) -> dict[str, Any]:
    """Map one valid mobile payload into the existing scalar CSV row shape."""

    frame = validate_mobile_feature_frame(payload)
    server_received = _optional_float(server_received_epoch_s)
    row: dict[str, Any] = {
        "frame_id": frame["frame_id"],
        "time_s": round(frame["phone_monotonic_ns"] / 1_000_000_000.0, 6),
        "mobile_payload_schema_version": frame["schema_version"],
        "mobile_source_platform": frame["source_platform"],
        "mobile_device_id": frame["device_id"],
        "mobile_run_id": frame["run_id"],
        "mobile_phone_monotonic_ns": frame["phone_monotonic_ns"],
        "mobile_phone_epoch_s": frame["phone_epoch_s"],
    }
    if server_received is not None:
        row["mobile_server_received_epoch_s"] = server_received
    offset_ms = frame.get("clock_offset_ms")
    jitter_ms = frame.get("clock_jitter_ms")
    if offset_ms is not None:
        row["mobile_clock_offset_ms"] = round(float(offset_ms), 6)
        row["sync_offset_ms"] = round(float(offset_ms), 6)
    if jitter_ms is not None:
        row["mobile_clock_jitter_ms"] = round(float(jitter_ms), 6)
    row["sync_method"] = "mobile_ping_pong"
    row["sync_quality"] = _sync_quality(offset_ms, jitter_ms)
    warning = _sync_warning(offset_ms, jitter_ms)
    if warning:
        row["sync_warning"] = warning

    if mobile_drop_count := frame.get("mobile_drop_count"):
        row["mobile_drop_count"] = _safe_number(mobile_drop_count, key="mobile_drop_count")
    if frame.get("mobile_stale_frame") is not None:
        row["mobile_stale_frame"] = bool(frame.get("mobile_stale_frame"))

    visible = frame.get("visible")
    if isinstance(visible, Mapping):
        _map_visible(row, visible)
    thermal = frame.get("thermal")
    if isinstance(thermal, Mapping):
        _map_thermal(row, thermal)
    return row


def estimate_clock_sync(samples: Iterable[Mapping[str, Any]]) -> ClockSyncResult:
    """Estimate phone->server clock offset using NTP-style ping/pong samples."""

    parsed: list[tuple[float, float]] = []
    for sample in samples:
        c0 = _required_float(sample, "client_send_epoch_s")
        s1 = _required_float(sample, "server_receive_epoch_s")
        s2 = _required_float(sample, "server_reply_epoch_s")
        c3 = _required_float(sample, "client_receive_epoch_s")
        rtt_s = (c3 - c0) - (s2 - s1)
        if rtt_s < 0:
            raise MobileProtocolError("clock sync sample has negative RTT")
        offset_s = ((s1 - c0) + (s2 - c3)) / 2.0
        parsed.append((offset_s * 1000.0, rtt_s * 1000.0))
    if not parsed:
        raise MobileProtocolError("at least one clock sync sample is required")
    best_offset, best_rtt = min(parsed, key=lambda item: item[1])
    offsets = [item[0] for item in parsed]
    jitter = statistics.pstdev(offsets) if len(offsets) > 1 else 0.0
    return ClockSyncResult(
        offset_ms=round(best_offset, 6),
        jitter_ms=round(jitter, 6),
        rtt_ms=round(best_rtt, 6),
        sample_count=len(parsed),
        quality=_sync_quality(best_offset, jitter),
    )


def generate_fake_mobile_frames(
    *,
    duration_s: float,
    fps: float = 25.0,
    device_id: str = "fake-android",
    run_id: str = "fake-run",
) -> Iterable[dict[str, Any]]:
    """Yield deterministic fake Android payloads for 25 Hz bridge/load tests."""

    duration = _positive_float(duration_s, "duration_s")
    rate = _positive_float(fps, "fps")
    count = int(round(duration * rate))
    step_ns = int(round(1_000_000_000.0 / rate))
    for frame_id in range(count):
        t_s = frame_id / rate
        raw = 5000.0 + frame_id * 0.1
        yield {
            "schema_version": MOBILE_FRAME_SCHEMA_VERSION,
            "source_platform": "android",
            "device_id": device_id,
            "run_id": run_id,
            "frame_id": frame_id,
            "phone_monotonic_ns": frame_id * step_ns,
            "phone_epoch_s": 1_700_000_000.0 + t_s,
            "clock_offset_ms": 0.0,
            "clock_jitter_ms": 0.0,
            "visible": {
                "frame_width": 640,
                "frame_height": 480,
                "roi": {"x": 100, "y": 120, "width": 180, "height": 160, "shape": "rectangle"},
                "features": {
                    "R_mean": 100.0 + (frame_id % 20),
                    "G_mean": 90.0,
                    "B_mean": 80.0,
                    "H_mean": (30.0 + frame_id * 0.25) % 360.0,
                    "S_mean": 0.4,
                    "V_mean": 0.5,
                    "H_delta": 0.25 if frame_id else 0.0,
                    "S_delta": 0.0,
                    "V_delta": 0.0,
                    "HSV_delta": 0.001 if frame_id else 0.0,
                    "color_delta": 1.0 if frame_id else 0.0,
                },
            },
            "thermal": {
                "frame_width": 256,
                "frame_height": 192,
                "calibrated": False,
                "conversion_model": "fake_android_raw_unverified",
                "roi": {"x": 80, "y": 70, "width": 48, "height": 48},
                "raw_roi": {"avg": raw, "min": raw - 10, "max": raw + 10, "p50": raw, "p95": raw + 8},
                "raw_matrix": {"min": raw - 200, "max": raw + 200, "mean": raw, "p95": raw + 160},
            },
        }


def assess_expected_frame_count(
    *, actual_count: int, duration_s: float, fps: float = 25.0, min_fraction: float = 0.9
) -> FrameCountAssessment:
    """Assess whether a fake/real ingest run met the expected frame count."""

    expected = int(round(_positive_float(duration_s, "duration_s") * _positive_float(fps, "fps")))
    minimum = int(math.ceil(expected * _positive_float(min_fraction, "min_fraction")))
    actual = _required_int({"actual_count": actual_count}, "actual_count", minimum=0)
    fraction = 0.0 if expected <= 0 else actual / expected
    return FrameCountAssessment(
        ok=actual >= minimum,
        expected_count=expected,
        minimum_count=minimum,
        actual_count=actual,
        fraction=round(fraction, 6),
    )


def _validate_sensor_block(value: Any, *, sensor: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MobileProtocolError(f"{sensor} block must be an object")
    block = dict(value)
    width = _required_int(block, "frame_width", minimum=1)
    height = _required_int(block, "frame_height", minimum=1)
    block["frame_width"] = width
    block["frame_height"] = height
    if "roi" in block and block["roi"] is not None:
        block["roi"] = _validate_roi(block["roi"], frame_width=width, frame_height=height, sensor=sensor)
    for key in ("features", "raw_roi", "raw_matrix", "celsius_roi", "celsius_matrix"):
        if key in block and block[key] is not None:
            block[key] = _validate_numeric_mapping(block[key], label=f"{sensor}.{key}")
    if sensor == "thermal":
        block["calibrated"] = bool(block.get("calibrated", False))
        block["conversion_model"] = str(block.get("conversion_model") or "").strip()[:160]
    return block


def _validate_roi(value: Any, *, frame_width: int, frame_height: int, sensor: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MobileProtocolError(f"{sensor} ROI must be an object")
    roi = dict(value)
    x = _required_int(roi, "x", minimum=0)
    y = _required_int(roi, "y", minimum=0)
    width = _required_int(roi, "width", minimum=1)
    height = _required_int(roi, "height", minimum=1)
    if x + width > frame_width or y + height > frame_height:
        raise MobileProtocolError(f"{sensor} ROI must fit inside frame")
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "shape": str(roi.get("shape") or "rectangle").strip()[:40] or "rectangle",
    }


def _validate_numeric_mapping(value: Any, *, label: str) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise MobileProtocolError(f"{label} must be an object")
    out: dict[str, float] = {}
    for key, raw in value.items():
        out[str(key)] = _safe_number(raw, key=f"{label}.{key}")
    return out


def _map_visible(row: dict[str, Any], visible: Mapping[str, Any]) -> None:
    row["visible_frame_width"] = visible.get("frame_width")
    row["visible_frame_height"] = visible.get("frame_height")
    if isinstance(visible.get("roi"), Mapping):
        _map_roi(row, visible["roi"], prefix="visible")
    features = visible.get("features")
    if isinstance(features, Mapping):
        for source, target in _VISIBLE_FEATURE_MAP.items():
            if source in features:
                row[target] = _safe_number(features[source], key=f"visible.features.{source}")


def _map_thermal(row: dict[str, Any], thermal: Mapping[str, Any]) -> None:
    row["thermal_source"] = "android_mobile"
    row["thermal_frame_width"] = thermal.get("frame_width")
    row["thermal_frame_height"] = thermal.get("frame_height")
    row["thermal_matrix_shape"] = f"{thermal.get('frame_height')}x{thermal.get('frame_width')}"
    row["thermal_calibrated"] = bool(thermal.get("calibrated", False))
    row["thermal_conversion_model"] = str(thermal.get("conversion_model") or "").strip()
    row["thermal_conversion_calibration_source"] = "android_mobile" if row["thermal_calibrated"] else "unverified_raw"
    if isinstance(thermal.get("roi"), Mapping):
        _map_roi(row, thermal["roi"], prefix="thermal")
    if isinstance(thermal.get("raw_roi"), Mapping):
        _map_summary(row, thermal["raw_roi"], prefix="thermal_raw_roi", mapping=_ROI_SUMMARY_MAP)
    if isinstance(thermal.get("raw_matrix"), Mapping):
        _map_summary(row, thermal["raw_matrix"], prefix="thermal_raw", mapping=_MATRIX_SUMMARY_MAP)
    if row["thermal_calibrated"]:
        if isinstance(thermal.get("celsius_roi"), Mapping):
            _map_summary(row, thermal["celsius_roi"], prefix="thermal_roi", mapping=_ROI_SUMMARY_MAP)
        if isinstance(thermal.get("celsius_matrix"), Mapping):
            _map_summary(row, thermal["celsius_matrix"], prefix="thermal_matrix", mapping=_MATRIX_SUMMARY_MAP)


def _map_roi(row: dict[str, Any], roi: Mapping[str, Any], *, prefix: str) -> None:
    row[f"{prefix}_roi_x"] = roi.get("x")
    row[f"{prefix}_roi_y"] = roi.get("y")
    row[f"{prefix}_roi_width"] = roi.get("width")
    row[f"{prefix}_roi_height"] = roi.get("height")
    row[f"{prefix}_roi_shape"] = roi.get("shape") or "rectangle"


def _map_summary(row: dict[str, Any], values: Mapping[str, Any], *, prefix: str, mapping: Mapping[str, str]) -> None:
    for source, suffix in mapping.items():
        if source in values:
            row[f"{prefix}_{suffix}"] = _safe_number(values[source], key=f"{prefix}.{source}")


def _sync_quality(offset_ms: Any, jitter_ms: Any) -> str:
    offset = abs(float(offset_ms)) if offset_ms is not None else 0.0
    jitter = float(jitter_ms) if jitter_ms is not None else 0.0
    if offset > 80.0 or jitter > 40.0:
        return "bad"
    if offset > 40.0 or jitter > 20.0:
        return "warn"
    return "good"


def _sync_warning(offset_ms: Any, jitter_ms: Any) -> str:
    quality = _sync_quality(offset_ms, jitter_ms)
    if quality == "bad":
        return "mobile clock sync bad"
    if quality == "warn":
        return "mobile clock sync warning"
    return ""


def _required_int(mapping: Mapping[str, Any], key: str, *, minimum: int | None = None) -> int:
    value = mapping.get(key)
    if isinstance(value, bool):
        raise MobileProtocolError(f"{key} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise MobileProtocolError(f"{key} must be an integer") from None
    if minimum is not None and parsed < minimum:
        raise MobileProtocolError(f"{key} must be >= {minimum}")
    return parsed


def _required_float(mapping: Mapping[str, Any], key: str, *, minimum: float | None = None) -> float:
    return _safe_number(mapping.get(key), key=key, minimum=minimum)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return _safe_number(value, key="value")


def _positive_float(value: Any, key: str) -> float:
    return _safe_number(value, key=key, minimum=0.0, strict_positive=True)


def _safe_number(value: Any, *, key: str, minimum: float | None = None, strict_positive: bool = False) -> float:
    if isinstance(value, bool):
        raise MobileProtocolError(f"{key} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise MobileProtocolError(f"{key} must be numeric") from None
    if not math.isfinite(parsed):
        raise MobileProtocolError(f"{key} must be finite")
    if strict_positive and parsed <= 0:
        raise MobileProtocolError(f"{key} must be > 0")
    if minimum is not None and parsed < minimum:
        raise MobileProtocolError(f"{key} must be >= {minimum}")
    return round(parsed, 6)
