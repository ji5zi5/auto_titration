"""OpenCV live preview with center ROI feature readout.

Mini2-like USB streams may expose a processed RGB frame, a green-ish luma frame,
or a vendor-specific preview that does not match the official app. This tool
records the original OpenCV frame channel values as raw_ch* CSV fields before
any display palette is applied. The values are stream pixels, not calibrated
temperature.
"""

from __future__ import annotations

import argparse
import csv
import math
import time
from datetime import datetime
from pathlib import Path


def backend_value(cv2, backend: str | None):  # type: ignore[no-untyped-def]
    if backend in (None, "", "any", "auto"):
        return None
    mapping = {"msmf": "CAP_MSMF", "dshow": "CAP_DSHOW"}
    attr = mapping.get(backend.lower())
    if attr is None or not hasattr(cv2, attr):
        raise ValueError(f"unsupported backend: {backend}")
    return getattr(cv2, attr)


def rgb_to_hsv_mean(bgr_roi):  # type: ignore[no-untyped-def]
    import cv2  # type: ignore[import-not-found]

    rgb = cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2RGB)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype("float64")
    rgb_mean = rgb.astype("float64").mean(axis=(0, 1))
    hsv_mean = hsv.mean(axis=(0, 1))
    # OpenCV hue is 0..179; convert to degrees for consistency.
    return {
        "R_mean": round(float(rgb_mean[0]), 6),
        "G_mean": round(float(rgb_mean[1]), 6),
        "B_mean": round(float(rgb_mean[2]), 6),
        "H_mean": round(float(hsv_mean[0] * 2.0), 6),
        "S_mean": round(float(hsv_mean[1] / 255.0), 6),
        "V_mean": round(float(hsv_mean[2] / 255.0), 6),
    }


def color_delta(current: dict[str, float], previous: dict[str, float] | None) -> float:
    if previous is None:
        return 0.0
    return round(
        math.sqrt(
            (current["R_mean"] - previous["R_mean"]) ** 2
            + (current["G_mean"] - previous["G_mean"]) ** 2
            + (current["B_mean"] - previous["B_mean"]) ** 2
        ),
        6,
    )


def hue_delta_deg(current_h: float, previous_h: float) -> float:
    diff = abs((float(current_h) - float(previous_h)) % 360.0)
    return min(diff, 360.0 - diff)


def hsv_delta(current: dict[str, float], previous: dict[str, float] | None) -> dict[str, float]:
    if previous is None:
        return {"H_delta": 0.0, "S_delta": 0.0, "V_delta": 0.0, "HSV_delta": 0.0}
    h_delta = hue_delta_deg(current["H_mean"], previous["H_mean"])
    s_delta = abs(current["S_mean"] - previous["S_mean"])
    v_delta = abs(current["V_mean"] - previous["V_mean"])
    return {
        "H_delta": round(h_delta, 6),
        "S_delta": round(s_delta, 6),
        "V_delta": round(v_delta, 6),
        "HSV_delta": round(math.sqrt((h_delta / 180.0) ** 2 + s_delta**2 + v_delta**2), 6),
    }


def ensure_bgr_frame(cv2, frame):  # type: ignore[no-untyped-def]
    if len(frame.shape) == 2:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    if frame.shape[2] == 4:
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    return frame


def raw_channel_stats(raw_roi, max_channels: int = 4) -> dict[str, str | int | float]:  # type: ignore[no-untyped-def]
    stats: dict[str, str | int | float] = {
        "raw_shape": "x".join(str(part) for part in raw_roi.shape),
        "raw_dtype": str(raw_roi.dtype),
    }
    channels = [raw_roi] if len(raw_roi.shape) == 2 else [raw_roi[:, :, index] for index in range(raw_roi.shape[2])]
    stats["raw_channels"] = len(channels)

    for index, channel in enumerate(channels[:max_channels]):
        values = channel.astype("float64")
        stats[f"raw_ch{index}_mean"] = round(float(values.mean()), 6)
        stats[f"raw_ch{index}_min"] = round(float(values.min()), 6)
        stats[f"raw_ch{index}_max"] = round(float(values.max()), 6)
        stats[f"raw_ch{index}_std"] = round(float(values.std()), 6)
    return stats


def extract_intensity_image(cv2, bgr_frame, channel: str):  # type: ignore[no-untyped-def]
    if channel == "gray":
        return cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2GRAY)
    channel_index = {"b": 0, "g": 1, "r": 2}[channel]
    return bgr_frame[:, :, channel_index]


def choose_intensity_channel(cv2, bgr_roi, requested: str) -> str:  # type: ignore[no-untyped-def]
    if requested != "auto":
        return requested

    candidates = {
        "gray": cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2GRAY),
        "b": bgr_roi[:, :, 0],
        "g": bgr_roi[:, :, 1],
        "r": bgr_roi[:, :, 2],
    }
    # Pick the channel with the most contrast in the ROI. For green-looking
    # Mini2 streams this usually selects G, then remaps it to a useful palette.
    return max(candidates, key=lambda name: float(candidates[name].std()))


def intensity_features(intensity_roi, previous_mean: float | None) -> dict[str, float]:  # type: ignore[no-untyped-def]
    values = intensity_roi.astype("float64")
    mean = float(values.mean())
    delta = 0.0 if previous_mean is None else abs(mean - previous_mean)
    return {
        "intensity_mean": round(mean, 6),
        "intensity_min": round(float(values.min()), 6),
        "intensity_max": round(float(values.max()), 6),
        "intensity_delta": round(delta, 6),
    }


def normalize_to_uint8(intensity_image):  # type: ignore[no-untyped-def]
    import numpy as np  # type: ignore[import-not-found]

    values = intensity_image.astype("float32")
    low, high = np.percentile(values, [1, 99])
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        low, high = float(values.min()), float(values.max())
    if high <= low:
        return np.zeros(values.shape, dtype="uint8")
    normalized = (values - low) * (255.0 / (high - low))
    return np.clip(normalized, 0, 255).astype("uint8")


def colormap_value(cv2, display: str) -> int:  # type: ignore[no-untyped-def]
    mapping = {
        "inferno": "COLORMAP_INFERNO",
        "turbo": "COLORMAP_TURBO",
        "magma": "COLORMAP_MAGMA",
        "plasma": "COLORMAP_PLASMA",
        "viridis": "COLORMAP_VIRIDIS",
        "jet": "COLORMAP_JET",
        "hot": "COLORMAP_HOT",
        "iron": "COLORMAP_HOT",
    }
    attr = mapping[display]
    return getattr(cv2, attr, cv2.COLORMAP_JET)


def render_display_frame(cv2, bgr_frame, intensity_image, display: str):  # type: ignore[no-untyped-def]
    if display == "raw":
        return bgr_frame.copy()
    normalized = normalize_to_uint8(intensity_image)
    if display == "gray":
        return cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR)
    return cv2.applyColorMap(normalized, colormap_value(cv2, display))


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview a camera index/backend and optionally record ROI CSV.")
    parser.add_argument("--index", type=int, default=1)
    parser.add_argument("--backend", default="msmf", help="any, msmf, or dshow")
    parser.add_argument("--output", default=None, help="Optional CSV output path")
    parser.add_argument("--source", default="thermal", help="CSV prefix/source label")
    parser.add_argument(
        "--display",
        default="raw",
        choices=["raw", "gray", "inferno", "turbo", "magma", "plasma", "viridis", "jet", "hot", "iron"],
        help="Preview rendering. raw shows the camera stream; palettes are display-only.",
    )
    parser.add_argument(
        "--intensity-channel",
        default="auto",
        choices=["auto", "gray", "r", "g", "b"],
        help="Signal used for relative thermal/intensity features. auto chooses the ROI channel with most contrast.",
    )
    parser.add_argument(
        "--raw-read",
        action="store_true",
        help="Try cv2.CAP_PROP_CONVERT_RGB=0 before reading. Some backends ignore this; CSV still records returned raw channels.",
    )
    args = parser.parse_args()

    import cv2  # type: ignore[import-not-found]

    value = backend_value(cv2, args.backend)
    cap = cv2.VideoCapture(args.index, value) if value is not None else cv2.VideoCapture(args.index)
    if not cap.isOpened():
        raise RuntimeError(f"could not open camera index={args.index} backend={args.backend}")
    if args.raw_read and hasattr(cv2, "CAP_PROP_CONVERT_RGB"):
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)

    output = Path(args.output or f"data/raw/preview-{args.source}-{datetime.now():%Y%m%d-%H%M%S}.csv")
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "time_s",
        "frame_id",
        f"{args.source}_R_mean",
        f"{args.source}_G_mean",
        f"{args.source}_B_mean",
        f"{args.source}_H_mean",
        f"{args.source}_S_mean",
        f"{args.source}_V_mean",
        f"{args.source}_H_delta",
        f"{args.source}_S_delta",
        f"{args.source}_V_delta",
        f"{args.source}_HSV_delta",
        f"{args.source}_color_delta",
        f"{args.source}_intensity_channel",
        f"{args.source}_intensity_mean",
        f"{args.source}_intensity_min",
        f"{args.source}_intensity_max",
        f"{args.source}_intensity_delta",
        f"{args.source}_raw_shape",
        f"{args.source}_raw_dtype",
        f"{args.source}_raw_channels",
    ]
    for channel_index in range(4):
        for stat_name in ("mean", "min", "max", "std"):
            fields.append(f"{args.source}_raw_ch{channel_index}_{stat_name}")
    start = time.monotonic()
    frame_id = 0
    previous_color = None
    previous_intensity_mean = None
    print("Press q or ESC to quit. CSV:", output)
    print(
        "Display:",
        args.display,
        "| intensity:",
        args.intensity_channel,
        "| raw_read:",
        args.raw_read,
        "| note: raw_ch* are original returned stream pixels, not calibrated temperature",
    )
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                print("frame read failed")
                break
            raw_frame = frame
            bgr_frame = ensure_bgr_frame(cv2, frame)
            h, w = bgr_frame.shape[:2]
            roi_w, roi_h = max(1, w // 2), max(1, h // 2)
            x, y = (w - roi_w) // 2, (h - roi_h) // 2
            roi = bgr_frame[y : y + roi_h, x : x + roi_w]
            raw_roi = raw_frame[y : y + roi_h, x : x + roi_w]
            raw_features = raw_channel_stats(raw_roi)
            features = rgb_to_hsv_mean(roi)
            features["color_delta"] = color_delta(features, previous_color)
            features.update(hsv_delta(features, previous_color))
            previous_color = features
            intensity_channel = choose_intensity_channel(cv2, roi, args.intensity_channel)
            intensity_full = extract_intensity_image(cv2, bgr_frame, intensity_channel)
            intensity_roi = intensity_full[y : y + roi_h, x : x + roi_w]
            intensity = intensity_features(intensity_roi, previous_intensity_mean)
            previous_intensity_mean = intensity["intensity_mean"]

            row = {"time_s": round(time.monotonic() - start, 3), "frame_id": frame_id}
            for key, value in features.items():
                row[f"{args.source}_{key}"] = value
            row[f"{args.source}_intensity_channel"] = intensity_channel
            for key, value in intensity.items():
                row[f"{args.source}_{key}"] = value
            for key, value in raw_features.items():
                row[f"{args.source}_{key}"] = value
            writer.writerow(row)
            fh.flush()

            display_frame = render_display_frame(cv2, bgr_frame, intensity_full, args.display)
            label = (
                f"{args.source} {args.display} raw0={raw_features.get('raw_ch0_mean', 0):.1f} "
                f"shape={raw_features['raw_shape']}"
            )
            label2 = (
                f"RGB=({features['R_mean']:.1f},{features['G_mean']:.1f},{features['B_mean']:.1f}) "
                "CSV raw_ch*=original returned pixels"
            )
            cv2.rectangle(display_frame, (x, y), (x + roi_w, y + roi_h), (0, 255, 0), 2)
            cv2.putText(display_frame, label, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.putText(display_frame, label2, (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.imshow(f"camera {args.index} {args.backend} {args.display}", display_frame)
            frame_id += 1
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
    cap.release()
    cv2.destroyAllWindows()
    print("saved:", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
