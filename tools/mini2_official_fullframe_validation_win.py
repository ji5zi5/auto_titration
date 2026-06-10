#!/usr/bin/env python3
"""Validate the official Mini2 full-frame converter against Analyzer CSV exports.

This script runs with Windows Python because it loads HIKMICRO's MTlib_OL.dll.
It does not fit formulas or use CSV values for conversion. The converter calls
the official MT_Process_INT path for each unique raw gray value in the frame and
expands those official results back to the full 256x192 matrix. It reports both
continuous Celsius error and Analyzer CSV-style one-decimal truncation parity.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.mini2_live import MINI2_MATRIX_SHAPE  # noqa: E402
from auto_titrator.official_hikmicro import (  # noqa: E402
    DLL_DIR_DEFAULT,
    OfficialMtlibConverter,
    analyzer_csv_truncate_0p1,
)


WIDTH = 256
HEIGHT = 192
PIXELS = WIDTH * HEIGHT


def csv_flat(path: Path) -> list[float]:
    text = None
    for enc in ("utf-8-sig", "cp949", "euc-kr", "latin1"):
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise RuntimeError(f"could not decode {path}")
    out: list[float] = []
    for row in csv.reader(text.splitlines()):
        nums: list[float] = []
        for cell in row:
            try:
                nums.append(float(cell.strip()))
            except ValueError:
                pass
        if len(nums) >= WIDTH:
            vals = nums[-WIDTH:]
            if max(vals) <= 150:
                out.extend(vals)
    if len(out) != PIXELS:
        raise RuntimeError(f"expected {PIXELS} CSV temperatures in {path}, got {len(out)}")
    return out


def raw_path_for(jpeg: Path) -> Path:
    path = ROOT / "data" / "mini2_multi_image_formula" / "raw" / f"{jpeg.stem}_lpld_raw_u16_256x192.bin"
    if not path.exists():
        raise RuntimeError(f"raw fixture not found: {path}")
    return path


def metrics(pred: np.ndarray, truth: list[float]) -> dict[str, object]:
    flat = pred.astype(np.float64, copy=False).reshape(-1)
    ref = np.asarray(truth, dtype=np.float64)
    finite = np.isfinite(flat)
    diffs = flat[finite] - ref[finite]
    rounded = np.round(flat[finite], 1) - ref[finite]
    worst_idx = np.argsort(np.abs(diffs))[-12:][::-1]
    finite_indices = np.nonzero(finite)[0]
    return {
        "count": int(diffs.size),
        "temp_min": float(np.min(flat[finite])),
        "temp_max": float(np.max(flat[finite])),
        "temp_mean": float(np.mean(flat[finite])),
        "mae": float(np.mean(np.abs(diffs))),
        "max_abs": float(np.max(np.abs(diffs))),
        "bias": float(np.mean(diffs)),
        "rounded_0p1_mae": float(np.mean(np.abs(rounded))),
        "rounded_0p1_max_abs": float(np.max(np.abs(rounded))),
        "rounded_0p1_match_rate": float(np.mean(np.abs(rounded) < 1e-9)),
        "count_abs_gt_0p05": int(np.sum(np.abs(diffs) > 0.05)),
        "count_abs_gt_0p10": int(np.sum(np.abs(diffs) > 0.10)),
        "worst_pairs": [
            [
                int(finite_indices[i]),
                int(finite_indices[i] // WIDTH),
                int(finite_indices[i] % WIDTH),
                float(flat[finite_indices[i]]),
                float(ref[finite_indices[i]]),
                float(flat[finite_indices[i]] - ref[finite_indices[i]]),
            ]
            for i in worst_idx
        ],
    }


def analyzer_csv_metrics(pred: np.ndarray, truth: list[float]) -> dict[str, object]:
    """Metrics after applying HIKMICRO Analyzer CSV one-decimal truncation."""

    display = analyzer_csv_truncate_0p1(pred).reshape(-1)
    ref = np.asarray(truth, dtype=np.float64)
    diffs = display - ref
    return {
        "count": int(diffs.size),
        "mae": float(np.mean(np.abs(diffs))),
        "max_abs": float(np.max(np.abs(diffs))),
        "bias": float(np.mean(diffs)),
        "match_rate": float(np.mean(np.abs(diffs) < 1e-9)),
        "mismatch_pixels": int(np.sum(np.abs(diffs) >= 1e-9)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    parser.add_argument("--fixtures", type=Path, default=ROOT / "data" / "fixtures" / "mini2")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "mini2_official_fullframe_validation" / "official_unique_gray_validation.json",
    )
    args = parser.parse_args(argv)

    records: list[dict[str, object]] = []
    for jpeg in sorted(args.fixtures.glob("IR_*.jpeg")):
        raw_path = raw_path_for(jpeg)
        raw = np.frombuffer(raw_path.read_bytes(), dtype="<u2").reshape(MINI2_MATRIX_SHAPE).copy()
        truth = csv_flat(jpeg.with_name(f"{jpeg.stem}_이미지.csv"))
        converter = OfficialMtlibConverter.from_jpeg(jpeg, dll_dir=args.dll_dir, batch_size=args.batch_size)
        started = time.perf_counter()
        matrix = converter.convert(raw)
        elapsed = time.perf_counter() - started
        converter.close()
        record = {
            "image": jpeg.stem,
            "jpeg": str(jpeg),
            "raw": str(raw_path),
            "raw_unique_count": int(np.unique(raw).size),
            "elapsed_s": elapsed,
            "fps_single_frame_equivalent": (1.0 / elapsed) if elapsed > 0 else math.inf,
            "converter": "official_mtprocess_unique_gray_fullframe",
            "dll_dir": str(args.dll_dir),
            "batch_size": args.batch_size,
            "matrix_shape": [HEIGHT, WIDTH],
            "validation_vs_analyzer_csv": metrics(matrix, truth),
            "validation_vs_analyzer_csv_truncate_0p1": analyzer_csv_metrics(matrix, truth),
        }
        records.append(record)
        v = record["validation_vs_analyzer_csv"]
        print(
            json.dumps(
                {
                    "image": record["image"],
                    "raw_unique_count": record["raw_unique_count"],
                    "elapsed_s": round(elapsed, 6),
                    "continuous_mae": v["mae"],
                    "continuous_max_abs": v["max_abs"],
                    "continuous_bias": v["bias"],
                    "truncate_0p1": record["validation_vs_analyzer_csv_truncate_0p1"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    summary = {
        "method": "official MT_Process_INT scaled-int unique-gray full-frame expansion",
        "notes": [
            "CSV is validation only; conversion calls HIKMICRO MTlib_OL.dll.",
            "This is not a fitted formula or CSV-derived lookup.",
            "It uses the traced MT_Process_INT point path while avoiding duplicate calls for repeated raw gray values.",
            "Analyzer CSV exports match floor(continuous_C * 10) / 10 for the Mini2 fixtures.",
        ],
        "records": records,
        "aggregate": {
            "image_count": len(records),
            "worst_mae": max(r["validation_vs_analyzer_csv"]["mae"] for r in records) if records else None,
            "worst_max_abs": max(r["validation_vs_analyzer_csv"]["max_abs"] for r in records) if records else None,
            "truncate_0p1_worst_mae": max(
                r["validation_vs_analyzer_csv_truncate_0p1"]["mae"] for r in records
            )
            if records
            else None,
            "truncate_0p1_worst_max_abs": max(
                r["validation_vs_analyzer_csv_truncate_0p1"]["max_abs"] for r in records
            )
            if records
            else None,
            "truncate_0p1_total_mismatch_pixels": sum(
                r["validation_vs_analyzer_csv_truncate_0p1"]["mismatch_pixels"] for r in records
            )
            if records
            else None,
            "mean_elapsed_s": float(np.mean([r["elapsed_s"] for r in records])) if records else None,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
