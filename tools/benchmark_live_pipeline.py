#!/usr/bin/env python3
"""Deterministic 25 fps evaluator for the live titration hot path.

This benchmark is hardware-free.  It proves queue/session/CSV semantics and
Python-side processing budget; the HIKMICRO DLL and physical cameras still need
the Windows hardware check reported by the collector itself.
"""

from __future__ import annotations

import argparse
import csv
import gc
import io
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.color_analysis import ColorFeatureExtractor, Roi, prefix_features  # noqa: E402
from auto_titrator.feature_history import FeatureSample  # noqa: E402
from auto_titrator.mini2_live import MINI2_IR_HEIGHT, MINI2_MATRIX_SHAPE, MINI2_UVC_HEIGHT, MINI2_UVC_WIDTH, Mini2RawFrameParts  # noqa: E402
from auto_titrator.ml_features import derive_ml_features, select_online_history_rows  # noqa: E402
from auto_titrator.official_hikmicro import OfficialMtlibConverter  # noqa: E402
from tools import windows_live_collect as live  # noqa: E402


class FixedRateMini2Reader:
    def __init__(
        self,
        *,
        frame_count: int,
        frame_rate_hz: float,
        raw_matrix: np.ndarray | None = None,
        addline_tag1: bytes | None = None,
    ) -> None:
        self.frame_count = int(frame_count)
        self.frame_rate_hz = float(frame_rate_hz)
        self.count = 0
        self.released = False
        self._start = time.perf_counter()
        self.raw_matrix = None if raw_matrix is None else np.asarray(raw_matrix, dtype="<u2")
        if self.raw_matrix is not None and self.raw_matrix.shape != MINI2_MATRIX_SHAPE:
            raise ValueError(f"saved Mini2 raw frame must have shape {MINI2_MATRIX_SHAPE}")
        self.addline_tag1 = addline_tag1
        if self.addline_tag1 is not None and len(self.addline_tag1) != 1024:
            raise ValueError("saved Mini2 addline must contain exactly 1024 bytes")

    def read_frame_parts(self) -> Mini2RawFrameParts:
        if self.count >= self.frame_count:
            raise EOFError("synthetic Mini2 sequence complete")
        target = self._start + self.count / self.frame_rate_hz
        delay = target - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        if self.raw_matrix is None:
            value = 5000 + self.count
            full = np.full((MINI2_UVC_HEIGHT, MINI2_UVC_WIDTH), value, dtype="<u2")
            full[MINI2_IR_HEIGHT : MINI2_IR_HEIGHT + 2, :] = np.arange(512, dtype=np.uint16).reshape(2, 256)
        else:
            full = np.empty((MINI2_UVC_HEIGHT, MINI2_UVC_WIDTH), dtype="<u2")
            full[:MINI2_IR_HEIGHT, :] = self.raw_matrix
            full[MINI2_IR_HEIGHT : MINI2_IR_HEIGHT + 2, :] = np.frombuffer(
                self.addline_tag1 or b"\x00" * 1024,
                dtype="<u2",
            ).reshape(2, MINI2_UVC_WIDTH)
        self.count += 1
        return Mini2RawFrameParts(
            raw_matrix=full[:MINI2_IR_HEIGHT, :],
            addline_tag1=full[MINI2_IR_HEIGHT : MINI2_IR_HEIGHT + 2, :].tobytes(),
            full_frame_u16=full,
        )

    def release(self) -> None:
        self.released = True


class VectorOfficialConverter:
    model_name = "benchmark_official_vector_converter"
    calibration_source = "deterministic_benchmark"
    calibrated = True

    def convert_values_with_addline(self, raw_values: np.ndarray, addline_tag1: bytes) -> np.ndarray:
        if len(addline_tag1) != 1024:
            raise ValueError("invalid addline")
        return np.asarray(raw_values, dtype=np.float64) / 64.0 - 55.0


def visible_frame(frame_id: int) -> np.ndarray:
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[..., 0] = 80 + frame_id % 80
    frame[..., 1] = 45
    frame[..., 2] = 120
    return frame


def verify_latest_preview() -> tuple[bool, list[int]]:
    state = live.LiveStreamState()
    entered = threading.Event()
    release = threading.Event()
    encoded: list[int] = []

    def encoder(frame: np.ndarray, *, quality: int) -> bytes:
        _ = quality
        value = int(frame[0, 0, 0])
        encoded.append(value)
        if len(encoded) == 1:
            entered.set()
            release.wait(1.0)
        return f"jpeg-{value}".encode("ascii")

    publisher = live.LiveJpegStreamPublisher(state, kind="visible", encoder=encoder, copy_frame=True)
    publisher.start()
    publisher.submit(visible_frame(1))
    if not entered.wait(1.0):
        publisher.close()
        return False, encoded
    publisher.submit(visible_frame(2))
    publisher.submit(visible_frame(3))
    release.set()
    deadline = time.monotonic() + 1.0
    while len(encoded) < 2 and time.monotonic() < deadline:
        time.sleep(0.005)
    publisher.close()
    expected = [int(visible_frame(1)[0, 0, 0]), int(visible_frame(3)[0, 0, 0])]
    return encoded == expected, encoded


def benchmark(args: argparse.Namespace) -> dict[str, Any]:
    converter: Any
    saved_raw: np.ndarray | None = None
    saved_addline: bytes | None = None
    if args.official_metadata_jpeg:
        converter = OfficialMtlibConverter.from_jpeg(
            args.official_metadata_jpeg,
            dll_dir=args.official_dll_dir,
        )
        saved_addline = converter.metadata.tag1
        if not args.official_raw_frame:
            raise ValueError("--official-raw-frame is required with --official-metadata-jpeg")
        saved_raw = np.fromfile(args.official_raw_frame, dtype="<u2")
        if saved_raw.size != MINI2_IR_HEIGHT * MINI2_UVC_WIDTH:
            raise ValueError("official raw frame must contain exactly 256x192 uint16 values")
        saved_raw = saved_raw.reshape(MINI2_MATRIX_SHAPE)
    else:
        converter = VectorOfficialConverter()
    reader = FixedRateMini2Reader(
        frame_count=args.frames,
        frame_rate_hz=args.target_fps,
        raw_matrix=saved_raw,
        addline_tag1=saved_addline,
    )
    start = time.perf_counter()
    worker = live.Mini2CaptureThread(
        reader,
        start_time=start,
        max_queue=1,
        max_recording_queue=max(64, int(args.frames)),
    )
    buffer = live.LiveCsvBuffer(output_path=Path("data/raw/benchmark-live.csv"))
    started = buffer.start_recording(started_monotonic_s=start, capture_session_required=True)
    session_id = int(started["session_id"])
    worker.begin_recording(session_id)
    worker.start()

    color = ColorFeatureExtractor()
    thermal_roi = Roi(96, 72, 64, 48)
    visible_roi = Roi(48, 36, 64, 48)
    previous_thermal: dict[str, object] | None = None
    previous_visible: dict[str, float] | None = None
    rows: list[dict[str, Any]] = []
    latencies_ms: list[float] = []
    stage_ms: dict[str, list[float]] = {
        "thermal": [],
        "visible": [],
        "row_and_ml": [],
        "csv": [],
    }

    gc_was_enabled = gc.isenabled()
    if gc_was_enabled:
        gc.disable()
    try:
        for _ in range(args.frames):
            captured = worker.read(timeout_s=2.0)
            stage_started = time.perf_counter()
            thermal = live.extract_roi_only_thermal_features(
                raw_matrix=captured.parts.raw_matrix,
                addline_tag1=captured.parts.addline_tag1,
                converter=converter,
                roi=thermal_roi,
                previous=previous_thermal,
                frame_rate_hz=args.target_fps,
            )
            stage_ms["thermal"].append((time.perf_counter() - stage_started) * 1000.0)
            previous_thermal = thermal
            stage_started = time.perf_counter()
            base_visible = color.extract(visible_frame(captured.frame_id), visible_roi, previous=previous_visible)
            stage_ms["visible"].append((time.perf_counter() - stage_started) * 1000.0)
            previous_visible = base_visible
            stage_started = time.perf_counter()
            sample = FeatureSample(
                time_s=captured.timestamp_s,
                frame_id=captured.frame_id,
                injected_volume_ml=captured.timestamp_s,
                visible_features=prefix_features(base_visible, "visible"),
                thermal_features=thermal,
                source_quality=str(thermal["source_quality"]),
            )
            row = sample.to_serializable_row()
            row["capture_recording_session_id"] = captured.recording_session_id
            row.update(live.build_sync_metadata(thermal_time_s=captured.timestamp_s, visible_time_s=captured.timestamp_s, max_sync_offset_ms=40.0))
            row.update(derive_ml_features(select_online_history_rows(rows, row), row))
            stage_ms["row_and_ml"].append((time.perf_counter() - stage_started) * 1000.0)
            latency_ms = max(0.0, (time.perf_counter() - (start + captured.timestamp_s)) * 1000.0)
            row["processing_latency_ms"] = round(latency_ms, 6)
            latencies_ms.append(latency_ms)
            rows.append(row)
            stage_started = time.perf_counter()
            if not buffer.add(row, now_monotonic_s=start + captured.timestamp_s):
                raise RuntimeError(f"CSV rejected recording frame {captured.frame_id}")
            stage_ms["csv"].append((time.perf_counter() - stage_started) * 1000.0)
            worker.mark_processed(captured)
    finally:
        if gc_was_enabled:
            gc.enable()
        capture_stop = worker.end_recording(session_id)
        buffer.request_stop()
        if worker.recording_drained(session_id):
            buffer.complete_stop()
        worker.close()
        close_converter = getattr(converter, "close", None)
        if callable(close_converter):
            close_converter()

    elapsed_s = time.perf_counter() - start
    csv_rows = list(csv.DictReader(io.StringIO(buffer.to_csv_bytes().decode("utf-8-sig"))))
    capture_status = worker.recording_status()
    preview_ok, encoded_preview_values = verify_latest_preview()
    frame_ids = [int(float(row["frame_id"])) for row in csv_rows]
    throughput_fps = len(csv_rows) / elapsed_s if elapsed_s > 0 else 0.0
    p95_latency_ms = float(np.percentile(latencies_ms, 95)) if latencies_ms else float("inf")
    failures: list[str] = []
    if len(csv_rows) != args.frames:
        failures.append(f"stored rows {len(csv_rows)} != captured target {args.frames}")
    if frame_ids != list(range(args.frames)):
        failures.append("CSV frame IDs are missing, duplicated, or out of order")
    if throughput_fps < args.min_throughput_fps:
        failures.append(f"throughput {throughput_fps:.3f} < {args.min_throughput_fps:.3f} fps")
    if p95_latency_ms > args.max_p95_latency_ms:
        failures.append(f"p95 latency {p95_latency_ms:.3f} > {args.max_p95_latency_ms:.3f} ms")
    if int(capture_status["recording_dropped_frames"]) > args.max_recording_drops:
        failures.append(
            f"recording drops {capture_status['recording_dropped_frames']} > {args.max_recording_drops}"
        )
    if int(capture_status["recording_backlog_frames"]) != 0 or not bool(capture_status["drained"]):
        failures.append("recording backlog did not drain")
    if int(capture_status["recording_max_backlog_frames"]) > max(64, args.frames):
        failures.append("recording backlog exceeded configured bound")
    if not preview_ok:
        failures.append(f"preview did not skip stale frame: encoded={encoded_preview_values}")

    return {
        "status": "pass" if not failures else "fail",
        "frames": args.frames,
        "converter": str(getattr(converter, "model_name", type(converter).__name__)),
        "stored_rows": len(csv_rows),
        "elapsed_s": round(elapsed_s, 6),
        "throughput_fps": round(throughput_fps, 6),
        "processing_latency_p95_ms": round(p95_latency_ms, 6),
        "processing_latency_max_ms": round(max(latencies_ms), 6) if latencies_ms else None,
        "stage_ms": {
            name: {
                "mean": round(float(np.mean(values)), 6),
                "p95": round(float(np.percentile(values, 95)), 6),
                "max": round(float(np.max(values)), 6),
            }
            for name, values in stage_ms.items()
        },
        "capture_status_at_stop": capture_stop,
        "capture_status_final": capture_status,
        "preview_latest_only": preview_ok,
        "preview_encoded_values": encoded_preview_values,
        "failures": failures,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=250)
    parser.add_argument("--target-fps", type=float, default=25.0)
    parser.add_argument("--min-throughput-fps", type=float, default=24.5)
    parser.add_argument("--max-p95-latency-ms", type=float, default=40.0)
    parser.add_argument("--max-recording-drops", type=int, default=0)
    parser.add_argument("--official-metadata-jpeg", default="")
    parser.add_argument("--official-raw-frame", default="")
    parser.add_argument("--official-dll-dir", default="vendor/hikmicro_analyzer")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.frames <= 0 or args.target_fps <= 0:
        raise SystemExit("frames and target fps must be positive")
    result = benchmark(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
