"""Probe Mini2 V4L2/UVC devices exposed in WSL/Linux.

This does not claim calibrated temperature. It determines whether /dev/video*
offers a raw-looking format such as Y16/GRAY16 or only display video such as
YUYV/MJPEG, then saves frame statistics and snapshots for inspection.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def run_command(command: list[str], timeout_s: float = 8.0) -> tuple[int, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s, check=False)
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except FileNotFoundError:
        return 127, f"command not found: {command[0]}"
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or "") + (exc.stderr or "") + "\nTIMEOUT"


def list_formats(device: str) -> str:
    _, output = run_command(["ffmpeg", "-hide_banner", "-f", "v4l2", "-list_formats", "all", "-i", device])
    return output


def parse_raw_format_candidates(format_text: str) -> list[tuple[str, str]]:
    """Return (pixel_format, WxH) candidates from ffmpeg V4L2 format listing."""
    candidates: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in format_text.splitlines():
        match = re.search(r"Raw\s*:\s*(\S+)\s*:", line)
        if not match:
            continue
        pixel_format = match.group(1)
        for size in re.findall(r"\b\d+x\d+\b", line):
            candidate = (pixel_format, size)
            if candidate not in seen:
                candidates.append(candidate)
                seen.add(candidate)
    return candidates


def raw_byte_stats(path: Path) -> dict[str, str | int | float]:
    if not path.exists() or path.stat().st_size <= 0:
        return {
            "raw_capture_bytes": 0,
            "raw_byte_mean": "",
            "raw_byte_std": "",
            "raw_byte_min": "",
            "raw_byte_max": "",
        }
    data = path.read_bytes()
    count = len(data)
    mean = sum(data) / count
    variance = sum((value - mean) ** 2 for value in data) / count
    return {
        "raw_capture_bytes": count,
        "raw_byte_mean": round(mean, 6),
        "raw_byte_std": round(math.sqrt(variance), 6),
        "raw_byte_min": min(data),
        "raw_byte_max": max(data),
    }


def capture_raw_frame(device: str, format_text: str, output_dir: Path, device_name: str) -> dict[str, str | int | float | bool]:
    candidates = parse_raw_format_candidates(format_text)
    if not candidates:
        return {
            "raw_capture_ok": False,
            "raw_capture_format": "",
            "raw_capture_size": "",
            "raw_capture_file": "",
            "raw_capture_error": "no ffmpeg raw V4L2 candidates found",
            **raw_byte_stats(output_dir / "missing.raw"),
        }

    last_error = ""
    for pixel_format, size in candidates[:12]:
        raw_path = output_dir / f"{device_name}_{pixel_format}_{size}.raw"
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "v4l2",
            "-input_format",
            pixel_format,
            "-video_size",
            size,
            "-i",
            device,
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-y",
            str(raw_path),
        ]
        code, output = run_command(command, timeout_s=10.0)
        if code == 0 and raw_path.exists() and raw_path.stat().st_size > 0:
            return {
                "raw_capture_ok": True,
                "raw_capture_format": pixel_format,
                "raw_capture_size": size,
                "raw_capture_file": str(raw_path),
                "raw_capture_error": "",
                **raw_byte_stats(raw_path),
            }
        if raw_path.exists() and raw_path.stat().st_size == 0:
            raw_path.unlink(missing_ok=True)
        last_error = f"{pixel_format} {size}: exit={code} {output.strip()[:240]}"

    return {
        "raw_capture_ok": False,
        "raw_capture_format": "",
        "raw_capture_size": "",
        "raw_capture_file": "",
        "raw_capture_error": last_error or "all raw capture attempts failed",
        **raw_byte_stats(output_dir / "missing.raw"),
    }


def probably_temperature_raw(format_text: str, frame: Any | None) -> bool:
    upper = format_text.upper()
    if any(token in upper for token in ("Y16", "GRAY16", "GREY16", "Z16", "16-BIT")):
        return True
    if frame is not None and len(frame.shape) == 2 and str(frame.dtype) in {"uint16", "int16"}:
        return True
    return False


def frame_stats(frame: Any | None) -> dict[str, str | int | float | bool]:
    if frame is None:
        return {
            "read_ok": False,
            "shape": "",
            "dtype": "",
            "frame_mean": "",
            "frame_std": "",
            "frame_min": "",
            "frame_max": "",
        }

    values = frame.astype("float64")
    return {
        "read_ok": True,
        "shape": "x".join(str(part) for part in frame.shape),
        "dtype": str(frame.dtype),
        "frame_mean": round(float(values.mean()), 6),
        "frame_std": round(float(values.std()), 6),
        "frame_min": round(float(values.min()), 6),
        "frame_max": round(float(values.max()), 6),
    }


def read_frame(device: str) -> tuple[Any | None, str]:
    import cv2  # type: ignore[import-not-found]

    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None, "cv2.VideoCapture could not open device"
    try:
        for _ in range(10):
            try:
                ok, frame = cap.read()
            except cv2.error as exc:
                return None, f"cv2.error: {exc}"
            if ok and frame is not None:
                return frame, ""
            time.sleep(0.1)
        return None, "no frame returned after retries"
    finally:
        cap.release()


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Mini2 /dev/video* V4L2 formats and frame stats.")
    parser.add_argument("--devices", nargs="*", default=["/dev/video0", "/dev/video1"])
    parser.add_argument("--output-dir", default=f"data/mini2_v4l2_probe/{datetime.now():%Y%m%d-%H%M%S}")
    args = parser.parse_args()

    import cv2  # type: ignore[import-not-found]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "v4l2_probe.csv"
    fields = [
        "device",
        "exists",
        "exists_before",
        "exists_after",
        "formats_summary",
        "probably_temperature_raw",
        "raw_capture_ok",
        "raw_capture_format",
        "raw_capture_size",
        "raw_capture_file",
        "raw_capture_bytes",
        "raw_byte_mean",
        "raw_byte_std",
        "raw_byte_min",
        "raw_byte_max",
        "raw_capture_error",
        "read_error",
        "read_ok",
        "shape",
        "dtype",
        "frame_mean",
        "frame_std",
        "frame_min",
        "frame_max",
        "snapshot",
    ]

    rows: list[dict[str, Any]] = []
    for device in args.devices:
        path = Path(device)
        exists_before = path.exists()
        format_text = list_formats(device) if exists_before else "device does not exist"
        raw_stats = capture_raw_frame(device, format_text, output_dir, path.name) if exists_before else {
            "raw_capture_ok": False,
            "raw_capture_format": "",
            "raw_capture_size": "",
            "raw_capture_file": "",
            "raw_capture_bytes": 0,
            "raw_byte_mean": "",
            "raw_byte_std": "",
            "raw_byte_min": "",
            "raw_byte_max": "",
            "raw_capture_error": "device does not exist",
        }
        frame, read_error = read_frame(device) if path.exists() else (None, "device does not exist")
        exists_after = path.exists()
        stats = frame_stats(frame)
        snapshot = ""
        if frame is not None:
            snapshot_path = output_dir / f"{path.name}.png"
            cv2.imwrite(str(snapshot_path), frame)
            snapshot = str(snapshot_path)

        row: dict[str, Any] = {
            "device": device,
            "exists": exists_before,
            "exists_before": exists_before,
            "exists_after": exists_after,
            "formats_summary": " | ".join(line.strip() for line in format_text.splitlines() if line.strip())[:1000],
            "probably_temperature_raw": probably_temperature_raw(format_text, frame),
            "read_error": read_error,
            "snapshot": snapshot,
        }
        row.update(raw_stats)
        row.update(stats)
        rows.append(row)

        (output_dir / f"{path.name}_formats.txt").write_text(format_text, encoding="utf-8")
        print(
            f"{device}: exists_before={row['exists_before']} exists_after={row['exists_after']} "
            f"read_ok={row['read_ok']} shape={row['shape']} "
            f"raw_capture_ok={row['raw_capture_ok']} raw_capture_bytes={row['raw_capture_bytes']} "
            f"probably_temperature_raw={row['probably_temperature_raw']}"
        )
        print(f"  raw: format={row['raw_capture_format']} size={row['raw_capture_size']} error={str(row['raw_capture_error'])[:180]}")
        print(f"  cv2: read_error={str(row['read_error'])[:180]}")
        print(f"  formats: {row['formats_summary'][:220]}")

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print("saved:", csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
