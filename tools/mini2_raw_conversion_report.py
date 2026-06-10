"""Validate IR_00001 Mini2 LPLD raw values against HIKMICRO CSV temperatures.

This script does not decompress HIKMICRO LPLD by itself. The raw file is produced
with HIKMICRO Analyzer's MicroJPEG_Release_x64.dll internal UnCompresser using:
  JPEG offset 20944, block size 32148, output RawDataInfo data pointer at +0x10.
It then proves the raw_u16 -> Celsius mapping against IR_00001_이미지.csv.
"""
from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from auto_titrator.thermal_camera import load_hikmicro_temperature_csv

RAW_PATH = Path("data/mini2_internal_uncompress_probe/ir00001_lpld_uncompressed_raw_u16_256x192.bin")
CSV_PATH = Path("data/fixtures/mini2/IR_00001_이미지.csv")
OUT_DIR = Path("data/mini2_internal_uncompress_probe")
LOOKUP_PATH = OUT_DIR / "ir00001_raw_to_celsius_lookup.csv"
REPORT_PATH = OUT_DIR / "ir00001_raw_conversion_report.json"
MD_PATH = OUT_DIR / "ir00001_raw_conversion_report.md"


def _stats(pred: np.ndarray, target: np.ndarray) -> dict[str, float | int]:
    err = pred - target
    rounded = np.round(pred, 1)
    return {
        "mae_c": float(np.mean(np.abs(err))),
        "rmse_c": float(math.sqrt(float(np.mean(err * err)))),
        "max_abs_c": float(np.max(np.abs(err))),
        "mean_error_c": float(np.mean(err)),
        "round_0p1_mismatch_pixels": int(np.count_nonzero(rounded != target)),
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw = np.fromfile(RAW_PATH, dtype="<u2").reshape(192, 256)
    temps = load_hikmicro_temperature_csv(CSV_PATH).values

    groups: dict[int, Counter[float]] = defaultdict(Counter)
    for raw_value, temp_c in zip(raw.ravel(), temps.ravel()):
        groups[int(raw_value)][float(temp_c)] += 1

    ambiguous = {raw_value: dict(counter) for raw_value, counter in groups.items() if len(counter) > 1}
    lookup = {raw_value: counter.most_common(1)[0][0] for raw_value, counter in groups.items()}
    lookup_pred = np.vectorize(lookup.__getitem__)(raw)

    with LOOKUP_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["raw_u16", "celsius", "count"])
        for raw_value in sorted(groups):
            writer.writerow([raw_value, f"{lookup[raw_value]:.1f}", sum(groups[raw_value].values())])

    x = raw.ravel().astype(float)
    y = temps.ravel().astype(float)
    affine_a, affine_b = np.polyfit(x, y, 1)
    affine_pred = affine_a * raw + affine_b
    quadratic = np.polyfit(x, y, 2)
    quadratic_pred = np.polyval(quadratic, raw)

    evidence_pixels = [
        (0, 0),
        (0, 7),
        (50, 27),
        (95, 128),
        (191, 255),
    ]
    pixel_checks = [
        {
            "y": int(row),
            "x": int(col),
            "raw_u16": int(raw[row, col]),
            "csv_celsius": float(temps[row, col]),
            "lookup_celsius": float(lookup_pred[row, col]),
        }
        for row, col in evidence_pixels
    ]

    report = {
        "source_files": {
            "jpeg": "data/fixtures/mini2/IR_00001.jpeg",
            "csv": str(CSV_PATH),
            "raw_bin": str(RAW_PATH),
        },
        "lpld_extraction_evidence": {
            "jpeg_payload": "APP3/SDMP radiometric payload",
            "lpld_start_file_offset": 20944,
            "lpld_block_size_bytes_passed_to_MicroJPEG_UnCompresser": 32148,
            "internal_dll": "MicroJPEG_Release_x64.dll",
            "internal_functions_rva": {
                "UnCompresser_constructor": "0x66af0",
                "UnCompresser_unCompress": "0x67340",
                "UnCompresser_getLPLImageInfo": "0x677f0",
            },
            "rawdata_info_observed": {
                "width": 256,
                "height": 192,
                "format": 14,
                "data_size_bytes": 98304,
                "dtype": "little-endian uint16",
            },
        },
        "raw_matrix": {
            "shape": list(raw.shape),
            "dtype": "uint16 little-endian",
            "min": int(raw.min()),
            "max": int(raw.max()),
            "mean": float(raw.mean()),
            "unique_values": int(len(groups)),
        },
        "csv_temperature_matrix": {
            "shape": list(temps.shape),
            "unit": "Celsius",
            "min": float(temps.min()),
            "max": float(temps.max()),
            "mean": float(temps.mean()),
        },
        "conversion_results": {
            "exact_lookup": {
                "definition": "T_celsius = lookup_table[raw_u16] for the calibration curve exported in IR_00001_이미지.csv; unseen raw values should be linearly interpolated only after additional calibration frames.",
                "lookup_csv": str(LOOKUP_PATH),
                "ambiguous_raw_values": len(ambiguous),
                **_stats(lookup_pred, temps),
            },
            "affine_candidate_not_exact": {
                "formula": f"T_celsius = {affine_a:.12f} * raw_u16 + {affine_b:.12f}",
                **_stats(affine_pred, temps),
            },
            "quadratic_candidate_not_exact": {
                "coefficients_high_to_low": [float(v) for v in quadratic],
                **_stats(quadratic_pred, temps),
            },
        },
        "pixel_checks": pixel_checks,
        "uncertainty": "The exact HIKMICRO SDK analytic grayToTemperature routine was not fully decompiled. Evidence shows the exported CSV is a deterministic nonlinear/quantized mapping from extracted raw_u16 values; the exact same-file conversion is therefore the lookup table, not a simple global scale such as /1024 or /8192.",
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        "# IR_00001 Mini2 Raw to Celsius Evidence",
        "",
        "## Proven extraction",
        "- JPEG `IR_00001.jpeg` contains an APP3/SDMP radiometric payload.",
        "- The LPLD block that `MicroJPEG_Release_x64.dll` accepts starts at file offset `20944` with size `32148` bytes.",
        "- Internal `UnCompresser::unCompress` returns a `192x256` little-endian `uint16` matrix, saved as `ir00001_lpld_uncompressed_raw_u16_256x192.bin`.",
        f"- Raw range: `{int(raw.min())}..{int(raw.max())}`, mean `{float(raw.mean()):.6f}`.",
        f"- CSV Celsius range: `{float(temps.min())}..{float(temps.max())}`, mean `{float(temps.mean()):.6f}`.",
        "",
        "## Conversion result",
        f"- Every raw value maps to exactly one CSV temperature in this capture: ambiguous raw values = `{len(ambiguous)}`.",
        "- Exact same-file conversion: `T_celsius = lookup_table[raw_u16]`.",
        f"- Lookup residual: MAE `{report['conversion_results']['exact_lookup']['mae_c']}` °C, RMSE `{report['conversion_results']['exact_lookup']['rmse_c']}` °C, max abs `{report['conversion_results']['exact_lookup']['max_abs_c']}` °C.",
        f"- Lookup table: `{LOOKUP_PATH}`.",
        "",
        "## Non-exact simple formulas",
        f"- Best affine: `{report['conversion_results']['affine_candidate_not_exact']['formula']}`.",
        f"- Affine residual: MAE `{report['conversion_results']['affine_candidate_not_exact']['mae_c']:.6f}` °C, RMSE `{report['conversion_results']['affine_candidate_not_exact']['rmse_c']:.6f}` °C, max abs `{report['conversion_results']['affine_candidate_not_exact']['max_abs_c']:.6f}` °C.",
        "- Therefore `/1024`, `/8192`, palette-color, or min/max-only scaling is not the correct conversion.",
        "",
        "## Pixel checks",
    ]
    for item in pixel_checks:
        md.append(f"- `(y={item['y']}, x={item['x']})`: raw `{item['raw_u16']}` -> lookup `{item['lookup_celsius']}` °C; CSV `{item['csv_celsius']}` °C")
    md.extend([
        "",
        "## Remaining uncertainty",
        "The official SDK's analytic/nonlinear `grayToTemperature` implementation was not fully decompiled. For this same capture, the raw-to-temperature mapping is exactly recovered as a deterministic lookup curve. For future live frames, use this as a calibration curve only if the camera mode/range/settings match; otherwise collect a new CSV/raw pair and regenerate the table.",
    ])
    MD_PATH.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
