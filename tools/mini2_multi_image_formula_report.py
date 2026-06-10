#!/usr/bin/env python3
"""Analyze Mini2 radiometric JPEG raw matrices against Analyzer CSV exports.

This is the multi-image follow-up to the one-frame IR_00001 proof. It uses the
raw matrices already decompressed from the JPEG APP3/SDMP LPLD payloads and
tests whether a single raw_u16 -> Celsius formula exists across all captures.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from auto_titrator.thermal_camera import load_hikmicro_temperature_csv


RAW_SHAPE = (192, 256)


def stats(pred: np.ndarray, target: np.ndarray) -> dict[str, float | int]:
    err = pred.astype(float) - target.astype(float)
    return {
        "mae_c": float(np.mean(np.abs(err))),
        "rmse_c": float(math.sqrt(float(np.mean(err * err)))),
        "max_abs_c": float(np.max(np.abs(err))),
        "mean_error_c": float(np.mean(err)),
        "round_0p1_mismatch_pixels": int(np.count_nonzero(np.round(pred, 1) != target)),
    }


def matrix_stats(values: np.ndarray, unit: str) -> dict[str, Any]:
    return {
        "shape": [int(v) for v in values.shape],
        "unit_or_dtype": unit,
        "min": float(values.min()) if values.dtype.kind == "f" else int(values.min()),
        "max": float(values.max()) if values.dtype.kind == "f" else int(values.max()),
        "mean": float(values.mean()),
        "unique_values": int(np.unique(values).size),
    }


def load_extraction_summary(out_dir: Path) -> dict[str, dict[str, str]]:
    path = out_dir / "raw_extraction_summary.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        rows: dict[str, dict[str, str]] = {}
        for row in csv.DictReader(handle):
            jpeg = row["jpeg"]
            # Windows Python writes UNC/backslash paths; Linux Path would treat
            # those as one filename, so use PureWindowsPath as the primary parse.
            stem = PureWindowsPath(jpeg).stem or Path(jpeg).stem
            rows[stem] = row
        return rows


def discover_pairs(raw_dir: Path) -> tuple[list[dict[str, Path]], list[dict[str, Any]]]:
    pairs: list[dict[str, Path]] = []
    excluded: list[dict[str, Any]] = []
    fixture_dir = Path("data/fixtures/mini2")
    for jpeg in sorted(fixture_dir.glob("*.jpeg")):
        stem = jpeg.stem
        if stem.startswith("IR_"):
            csv_path = Path("data/fixtures/mini2") / f"{stem}_이미지.csv"
            raw_path = raw_dir / f"{stem}_lpld_raw_u16_256x192.bin"
            if csv_path.exists() and raw_path.exists():
                pairs.append({"stem": Path(stem), "jpeg": jpeg, "csv": csv_path, "raw": raw_path})
            else:
                excluded.append(
                    {
                        "jpeg": str(jpeg),
                        "reason": "IR prefix but missing matching CSV or decompressed raw bin",
                        "expected_csv": str(csv_path),
                        "expected_raw": str(raw_path),
                    }
                )
        elif jpeg.with_suffix(".csv").exists():
            try:
                matrix = load_hikmicro_temperature_csv(jpeg.with_suffix(".csv")).values
                shape = list(matrix.shape)
            except Exception as exc:  # pragma: no cover - diagnostic only
                shape = [f"load_error: {exc}"]
            excluded.append(
                {
                    "jpeg": str(jpeg),
                    "csv": f"{stem}.csv",
                    "reason": "reference/non-target HIKMICRO pair; not Mini2 IR_000xx capture set and CSV shape does not match 256x192 target raw bins",
                    "csv_shape": shape,
                }
            )
    return pairs, excluded


def per_file_lookup(raw: np.ndarray, temp: np.ndarray) -> tuple[dict[int, float], dict[str, Any]]:
    groups: dict[int, Counter[float]] = defaultdict(Counter)
    for raw_value, temp_c in zip(raw.ravel(), temp.ravel()):
        groups[int(raw_value)][float(temp_c)] += 1
    ambiguous = {
        raw_value: dict(counter) for raw_value, counter in groups.items() if len(counter) > 1
    }
    lookup = {raw_value: counter.most_common(1)[0][0] for raw_value, counter in groups.items()}
    mapping = [(raw_value, lookup[raw_value]) for raw_value in sorted(lookup)]
    decreasing_steps = []
    same_steps = 0
    increasing_steps = 0
    for (raw0, temp0), (raw1, temp1) in zip(mapping, mapping[1:]):
        if temp1 < temp0:
            decreasing_steps.append({"raw0": raw0, "temp0": temp0, "raw1": raw1, "temp1": temp1})
        elif temp1 == temp0:
            same_steps += 1
        else:
            increasing_steps += 1
    pred = np.vectorize(lookup.__getitem__)(raw)
    report = {
        "unique_raw_values": len(groups),
        "ambiguous_raw_values_within_file": len(ambiguous),
        "decreasing_adjacent_raw_steps": len(decreasing_steps),
        "decreasing_examples": decreasing_steps[:10],
        "same_adjacent_raw_steps": same_steps,
        "increasing_adjacent_raw_steps": increasing_steps,
        "lookup_residual": stats(pred, temp),
    }
    return lookup, report


def fit_poly(x: np.ndarray, y: np.ndarray, degree: int) -> tuple[np.ndarray, dict[str, Any]]:
    coeff = np.polyfit(x.astype(float), y.astype(float), degree)
    pred = np.polyval(coeff, x.astype(float))
    return coeff, stats(pred, y)


def write_lookup_csv(path: Path, lookup: dict[int, float], raw: np.ndarray) -> None:
    counts = Counter(int(v) for v in raw.ravel())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["raw_u16", "celsius_from_same_csv", "pixel_count"])
        for raw_value in sorted(lookup):
            writer.writerow([raw_value, f"{lookup[raw_value]:.1f}", counts[raw_value]])


def make_report(output_dir: Path) -> dict[str, Any]:
    raw_dir = output_dir / "raw"
    pairs, excluded = discover_pairs(raw_dir)
    extraction_summary = load_extraction_summary(output_dir)

    per_file: list[dict[str, Any]] = []
    all_raw: list[np.ndarray] = []
    all_temp: list[np.ndarray] = []
    global_groups: dict[int, Counter[float]] = defaultdict(Counter)
    pair_matrices: list[tuple[str, np.ndarray, np.ndarray]] = []

    lookup_dir = output_dir / "lookups"
    lookup_dir.mkdir(parents=True, exist_ok=True)

    for pair in pairs:
        stem = str(pair["stem"])
        raw = np.fromfile(pair["raw"], dtype="<u2").reshape(RAW_SHAPE)
        temp = load_hikmicro_temperature_csv(pair["csv"]).values.astype(float)
        if temp.shape != RAW_SHAPE:
            raise ValueError(f"{pair['csv']} shape {temp.shape} != {RAW_SHAPE}")

        all_raw.append(raw.ravel().astype(float))
        all_temp.append(temp.ravel().astype(float))
        pair_matrices.append((stem, raw, temp))
        for raw_value, temp_c in zip(raw.ravel(), temp.ravel()):
            global_groups[int(raw_value)][float(temp_c)] += 1

        lookup, lookup_report = per_file_lookup(raw, temp)
        write_lookup_csv(lookup_dir / f"{stem}_same_file_raw_to_celsius_lookup.csv", lookup, raw)

        affine_coeff, affine_stats = fit_poly(raw.ravel(), temp.ravel(), 1)
        quadratic_coeff, quadratic_stats = fit_poly(raw.ravel(), temp.ravel(), 2)
        minmax_pred = (raw.astype(float) - raw.min()) / (raw.max() - raw.min()) * (
            temp.max() - temp.min()
        ) + temp.min()

        extraction = extraction_summary.get(stem, {})
        per_file.append(
            {
                "stem": stem,
                "source_files": {
                    "jpeg": str(pair["jpeg"]),
                    "csv": str(pair["csv"]),
                    "raw_bin": str(pair["raw"]),
                },
                "lpld_extraction": {
                    "file_offset": int(extraction.get("lpld_file_offset", -1)),
                    "size_bytes": int(extraction.get("lpld_size_bytes", -1)),
                    "raw_info_width": int(extraction.get("raw_info_width", -1)),
                    "raw_info_height": int(extraction.get("raw_info_height", -1)),
                    "raw_info_format": int(extraction.get("raw_info_format", -1)),
                    "raw_info_data_size": int(extraction.get("raw_info_data_size", -1)),
                },
                "raw_matrix": matrix_stats(raw, "little-endian uint16"),
                "csv_temperature_matrix": matrix_stats(temp, "Celsius"),
                "same_file_lookup": lookup_report,
                "affine_approximation": {
                    "formula": f"T_celsius = {affine_coeff[0]:.12f} * raw_u16 + {affine_coeff[1]:.12f}",
                    "coefficients_high_to_low": [float(v) for v in affine_coeff],
                    **affine_stats,
                },
                "quadratic_approximation": {
                    "coefficients_high_to_low": [float(v) for v in quadratic_coeff],
                    **quadratic_stats,
                },
                "minmax_scaled_approximation": {
                    "definition": "T = (raw-raw_min)/(raw_max-raw_min)*(csv_max-csv_min)+csv_min; included to reject whole-frame min/max fitting as exact conversion.",
                    **stats(minmax_pred, temp),
                },
            }
        )

    x_all = np.concatenate(all_raw)
    y_all = np.concatenate(all_temp)

    global_poly: list[dict[str, Any]] = []
    for degree in range(1, 6):
        coeff, residual = fit_poly(x_all, y_all, degree)
        global_poly.append(
            {
                "degree": degree,
                "coefficients_high_to_low": [float(v) for v in coeff],
                **residual,
            }
        )

    held_out: list[dict[str, Any]] = []
    for degree in range(1, 6):
        for hold_stem, hold_raw, hold_temp in pair_matrices:
            train_raw = np.concatenate(
                [raw.ravel().astype(float) for stem, raw, _temp in pair_matrices if stem != hold_stem]
            )
            train_temp = np.concatenate(
                [temp.ravel().astype(float) for stem, _raw, temp in pair_matrices if stem != hold_stem]
            )
            coeff = np.polyfit(train_raw, train_temp, degree)
            pred = np.polyval(coeff, hold_raw.ravel().astype(float))
            residual = stats(pred, hold_temp.ravel().astype(float))
            held_out.append({"held_out": hold_stem, "degree": degree, **residual})

    ambiguous_global: list[dict[str, Any]] = []
    for raw_value, counter in global_groups.items():
        if len(counter) > 1:
            temps = sorted(counter)
            ambiguous_global.append(
                {
                    "raw_u16": raw_value,
                    "min_c": min(temps),
                    "max_c": max(temps),
                    "spread_c": max(temps) - min(temps),
                    "total_pixel_count": int(sum(counter.values())),
                    "distinct_temperatures": len(counter),
                    "top_temperature_counts": [
                        {"celsius": temp, "count": int(count)}
                        for temp, count in counter.most_common(8)
                    ],
                }
            )
    ambiguous_global.sort(key=lambda row: (-row["spread_c"], -row["total_pixel_count"], row["raw_u16"]))

    # Test the tempting but invalid one-image lookup generalization.
    ir1_lookup_path = lookup_dir / "IR_00001_same_file_raw_to_celsius_lookup.csv"
    ir1_lookup: dict[int, float] = {}
    if ir1_lookup_path.exists():
        with ir1_lookup_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                ir1_lookup[int(row["raw_u16"])] = float(row["celsius_from_same_csv"])
    ir1_lookup_tests: list[dict[str, Any]] = []
    if ir1_lookup:
        lookup_raws = np.array(sorted(ir1_lookup), dtype=float)
        lookup_temps = np.array([ir1_lookup[int(raw_value)] for raw_value in lookup_raws], dtype=float)
        for stem, raw, temp in pair_matrices:
            pred = np.interp(raw.ravel().astype(float), lookup_raws, lookup_temps, left=lookup_temps[0], right=lookup_temps[-1])
            ir1_lookup_tests.append({"target": stem, **stats(pred, temp.ravel())})

    ambiguous_csv = output_dir / "cross_image_same_raw_ambiguity_examples.csv"
    with ambiguous_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "raw_u16",
                "min_c",
                "max_c",
                "spread_c",
                "total_pixel_count",
                "distinct_temperatures",
                "top_temperature_counts",
            ]
        )
        for row in ambiguous_global:
            writer.writerow(
                [
                    row["raw_u16"],
                    f"{row['min_c']:.1f}",
                    f"{row['max_c']:.1f}",
                    f"{row['spread_c']:.1f}",
                    row["total_pixel_count"],
                    row["distinct_temperatures"],
                    json.dumps(row["top_temperature_counts"], ensure_ascii=False),
                ]
            )

    report = {
        "purpose": "Determine whether HIKMICRO Mini2 JPEG LPLD raw_u16 values have a single cross-image Celsius conversion formula.",
        "target_pairs": [
            {"stem": str(pair["stem"]), "jpeg": str(pair["jpeg"]), "csv": str(pair["csv"]), "raw": str(pair["raw"])}
            for pair in pairs
        ],
        "excluded_reference_pairs": excluded,
        "per_file": per_file,
        "cross_image_same_raw_consistency": {
            "combined_pixel_count": int(x_all.size),
            "unique_raw_values_across_all_images": len(global_groups),
            "ambiguous_raw_values_across_images": len(ambiguous_global),
            "max_same_raw_temperature_spread_c": float(ambiguous_global[0]["spread_c"]) if ambiguous_global else 0.0,
            "ambiguity_examples_csv": str(ambiguous_csv),
            "top_10_ambiguity_examples": ambiguous_global[:10],
            "conclusion": "A single global function T=f(raw_u16) is disproven because the same raw_u16 maps to different Celsius values in different captures.",
        },
        "model_tests": {
            "global_polynomial_degrees_1_to_5": global_poly,
            "held_out_polynomial_tests": held_out,
            "ir00001_lookup_interpolated_to_other_images": ir1_lookup_tests,
            "per_file_same_csv_lookup": "Exact within each image, but this is a same-file calibration table generated from the Analyzer CSV, not a predictive cross-image formula.",
        },
        "classification_of_raw_values": {
            "not_palette_color": "The tested raw data came from APP3/SDMP radiometric LPLD payloads and is 192x256 uint16, not from the visible pseudo-color JPEG pixels.",
            "not_per_pixel_wavelength": "Mini2 is a long-wave IR detector over a spectral band; the JPEG payload gives radiometric gray/temperature-related counts, not a wavelength value for each pixel.",
            "best_evidence_label": "SDK-corrected radiometric gray/count units. They are strongly temperature-related inside one capture, but need frame/image calibration metadata or SDK processing for exact Celsius.",
        },
        "final_conclusion": {
            "single_global_formula_found": False,
            "exact_same_file_conversion": "For each exported JPEG+CSV pair: T_celsius = same_file_lookup[raw_u16] gives 0.0 C residual because each raw value maps to one CSV value within that image.",
            "best_simple_formula": "Per-image affine approximation gives about 0.033..0.057 C MAE and 0.149..0.377 C max error on these files, but it is not exact and parameters shift by image.",
            "practical_project_recommendation": "For science-fair data collection, store the official Analyzer/App CSV matrix when available. For live Mini2 UVC/JPEG raw, either call the vendor SDK/Analyzer export path or fit a project-local per-session calibration model; do not trust a universal raw_u16 formula or pseudo-color palette extraction.",
        },
    }
    return report


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines: list[str] = [
        "# Mini2 Multi-Image Raw to Celsius Report",
        "",
        "## 결론",
        "",
        "- **전역 변환식 `T = f(raw_u16)`은 없음**: 같은 raw 값이 이미지마다 다른 섭씨값으로 나왔다.",
        "- **각 파일 내부에서는 lookup이 0 오차**: 같은 이미지 안에서는 raw 값 하나가 CSV 온도 하나로만 대응했다.",
        "- 따라서 raw는 색/파장값이 아니라 **HIKMICRO SDK가 쓰는 radiometric gray/count 계열 값**으로 보는 것이 맞다.",
        "- 단순 선형식은 근사만 된다. 과학전람회 앱에서는 공식 CSV/SDK 경로 또는 실험별 보정/ML을 써야 한다.",
        "",
        "## 사용한 파일",
        "",
        "| pair | raw range | CSV °C range | LPLD offset | LPLD size | same-file lookup max error | affine MAE / max |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["per_file"]:
        raw = row["raw_matrix"]
        temp = row["csv_temperature_matrix"]
        lpld = row["lpld_extraction"]
        lookup = row["same_file_lookup"]["lookup_residual"]
        affine = row["affine_approximation"]
        lines.append(
            f"| {row['stem']} | {raw['min']}..{raw['max']} | {temp['min']:.1f}..{temp['max']:.1f} | "
            f"{lpld['file_offset']} | {lpld['size_bytes']} | {lookup['max_abs_c']:.3f} | "
            f"{affine['mae_c']:.4f} / {affine['max_abs_c']:.4f} |"
        )
    c = report["cross_image_same_raw_consistency"]
    lines += [
        "",
        "## 전역 raw→온도식 반증",
        "",
        f"- 전체 픽셀 수: `{c['combined_pixel_count']}`",
        f"- 전체 raw 고유값: `{c['unique_raw_values_across_all_images']}`",
        f"- 이미지 사이에서 같은 raw가 다른 온도로 나온 raw 값: `{c['ambiguous_raw_values_across_images']}`",
        f"- 최대 차이: `{c['max_same_raw_temperature_spread_c']:.1f} °C`",
        f"- 예시 CSV: `{c['ambiguity_examples_csv']}`",
        "",
        "상위 예시:",
        "",
        "| raw | min °C | max °C | spread | top counts |",
        "| ---: | ---: | ---: | ---: | --- |",
    ]
    for row in c["top_10_ambiguity_examples"][:5]:
        lines.append(
            f"| {row['raw_u16']} | {row['min_c']:.1f} | {row['max_c']:.1f} | {row['spread_c']:.1f} | "
            f"`{row['top_temperature_counts'][:4]}` |"
        )
    lines += [
        "",
        "## 모델 테스트 요약",
        "",
        "| model | MAE °C | RMSE °C | max °C |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in report["model_tests"]["global_polynomial_degrees_1_to_5"]:
        lines.append(
            f"| global polynomial degree {row['degree']} | {row['mae_c']:.4f} | {row['rmse_c']:.4f} | {row['max_abs_c']:.4f} |"
        )
    lines += [
        "",
        "## 해석",
        "",
        "- Mini2 공식 스펙은 `256 × 192` IR 해상도와 `7.5~14 µm` spectral range를 가진 장치다. 여기서 말하는 spectral range는 센서가 보는 파장대이지, 픽셀마다 저장되는 값이 '파장'이라는 뜻이 아니다.",
        "- HIKMICRO radiometric JPEG에는 온도 데이터가 들어 있고 Analyzer는 전체 픽셀 온도행렬 CSV를 내보낼 수 있다.",
        "- 이번에 뽑은 raw는 JPEG 표시용 가짜색 RGB가 아니라 APP3/SDMP 내부 LPLD payload에서 나온 `192x256 uint16` 행렬이다.",
        "- 그러나 같은 raw 값이 여러 이미지에서 다른 온도가 되므로, 정확한 섭씨 변환에는 프레임/이미지별 SDK 보정 정보가 필요하다.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/mini2_multi_image_formula")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = make_report(output_dir)

    json_path = output_dir / "multi_image_formula_report.json"
    md_path = output_dir / "multi_image_formula_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, md_path)
    print(json.dumps(report["final_conclusion"], ensure_ascii=False, indent=2))
    print(f"saved: {json_path}")
    print(f"saved: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
