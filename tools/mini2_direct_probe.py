"""Probe HIKMICRO Mini2 direct USB access on Windows.

This script does not decode Mini2 vendor USB data. It answers the first
question: is the device exposed as a normal Windows video camera stream, or only
as a vendor-specific USB device for HIKMICRO software?
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

VID_PID_RE = re.compile(r"VID_([0-9A-Fa-f]{4}).*PID_([0-9A-Fa-f]{4})")
KEYWORDS = ("HIK", "HIKMICRO", "THERM", "IR", "CAMERA", "UVC", "USB VIDEO")


def run_powershell_device_scan() -> list[dict[str, Any]]:
    """Return relevant Windows PnP devices using PowerShell, or [] elsewhere."""

    if platform.system().lower() != "windows":
        return []
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "Get-CimInstance Win32_PnPEntity | "
        "Where-Object { $_.PNPDeviceID -like '*USB*' -or $_.Name -match 'Camera|HIK|Therm|UVC|Video' } | "
        "Select-Object Name,PNPDeviceID,Manufacturer,Service,Status,ClassGuid | "
        "ConvertTo-Json -Depth 3",
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [{"error": f"PowerShell scan failed: {exc}"}]
    if result.returncode != 0:
        return [{"error": result.stderr.strip() or "PowerShell scan failed"}]
    text = result.stdout.strip()
    if not text:
        return []
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return [{"error": "PowerShell JSON parse failed", "raw": text[:2000]}]
    if isinstance(loaded, dict):
        return [loaded]
    return loaded if isinstance(loaded, list) else []


def annotate_devices(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated = []
    for device in devices:
        item = dict(device)
        haystack = " ".join(str(item.get(k, "")) for k in ("Name", "PNPDeviceID", "Manufacturer", "Service")).upper()
        item["looks_relevant"] = any(keyword in haystack for keyword in KEYWORDS)
        match = VID_PID_RE.search(str(item.get("PNPDeviceID", "")))
        if match:
            item["vid"] = match.group(1).upper()
            item["pid"] = match.group(2).upper()
        annotated.append(item)
    return annotated


def cv2_probe(max_index: int, output_dir: Path) -> list[dict[str, Any]]:
    """Try OpenCV camera capture indices/backends and save readable snapshots."""

    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np
    except ImportError as exc:
        return [{"error": f"opencv/numpy import failed: {exc}"}]

    backends: list[tuple[str, int]] = [("ANY", 0)]
    for name in ("CAP_DSHOW", "CAP_MSMF"):
        value = getattr(cv2, name, None)
        if value is not None:
            backends.append((name.replace("CAP_", ""), int(value)))

    rows: list[dict[str, Any]] = []
    for index in range(max_index):
        for backend_name, backend_value in backends:
            cap = cv2.VideoCapture(index, backend_value) if backend_value else cv2.VideoCapture(index)
            opened = bool(cap.isOpened())
            record: dict[str, Any] = {"index": index, "backend": backend_name, "opened": opened}
            if opened:
                ok = False
                frame = None
                for _ in range(8):
                    ok, frame = cap.read()
                    if ok and frame is not None:
                        break
                record["read_ok"] = bool(ok and frame is not None)
                if ok and frame is not None:
                    arr = np.asarray(frame)
                    record["shape"] = "x".join(str(v) for v in arr.shape)
                    record["mean"] = round(float(arr.mean()), 3)
                    record["std"] = round(float(arr.std()), 3)
                    record["probably_blank"] = bool(arr.std() < 2.0)
                    filename = f"opencv_index{index}_{backend_name}.png"
                    cv2.imwrite(str(output_dir / filename), frame)
                    record["snapshot"] = filename
                else:
                    record["read_ok"] = False
            cap.release()
            rows.append(record)
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def print_summary(devices: list[dict[str, Any]], captures: list[dict[str, Any]], output_dir: Path) -> int:
    relevant = [d for d in devices if d.get("looks_relevant")]
    readable = [c for c in captures if c.get("read_ok") and not c.get("probably_blank")]
    blank = [c for c in captures if c.get("read_ok") and c.get("probably_blank")]

    print("\n=== Mini2 direct probe summary ===")
    print(f"Output: {output_dir}")
    if devices:
        print("\nRelevant USB/video devices:")
        for d in relevant[:20]:
            vidpid = f" VID={d.get('vid')} PID={d.get('pid')}" if d.get("vid") else ""
            print(f"- {d.get('Name', '(no name)')} | Service={d.get('Service')} | Status={d.get('Status')}{vidpid}")
    else:
        print("\nWindows PnP scan was not available. Run this script in Windows PowerShell/CMD, not WSL.")

    print("\nOpenCV readable video streams:")
    if readable:
        for c in readable:
            print(f"- index {c['index']} backend {c['backend']} shape={c.get('shape')} mean={c.get('mean')} std={c.get('std')} snapshot={c.get('snapshot')}")
    else:
        print("- none")

    if blank:
        print("\nOpened but probably blank streams:")
        for c in blank:
            print(f"- index {c['index']} backend {c['backend']} shape={c.get('shape')} mean={c.get('mean')} std={c.get('std')} snapshot={c.get('snapshot')}")

    print("\nInterpretation:")
    if readable:
        print("- At least one normal Windows video stream works. If one snapshot is Mini2, use that index/backend.")
        return 0
    print("- No readable OpenCV video stream found. If Mini2 appears in relevant USB devices, it is likely vendor-specific, not a normal webcam stream.")
    print("- Next direct path is vendor USB reverse-engineering/SDK access: identify VID/PID, USB interfaces/endpoints, then test a compatible HIKMICRO/Hikvision USB SDK. This is experimental.")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe whether Mini2 is accessible as direct USB/UVC video on Windows.")
    parser.add_argument("--max-index", type=int, default=10, help="OpenCV camera indices to probe")
    parser.add_argument("--output", default=None, help="Output directory for JSON/CSV/snapshots")
    args = parser.parse_args()

    output_dir = Path(args.output or f"data/mini2_probe/{datetime.now():%Y%m%d-%H%M%S}")
    output_dir.mkdir(parents=True, exist_ok=True)

    devices = annotate_devices(run_powershell_device_scan())
    captures = cv2_probe(args.max_index, output_dir)

    (output_dir / "windows_pnp_devices.json").write_text(json.dumps(devices, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(output_dir / "opencv_capture_probe.csv", captures)
    (output_dir / "opencv_capture_probe.json").write_text(json.dumps(captures, indent=2, ensure_ascii=False), encoding="utf-8")

    return print_summary(devices, captures, output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
