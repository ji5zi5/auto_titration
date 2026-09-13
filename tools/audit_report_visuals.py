#!/usr/bin/env python3
"""Audit science-fair report visual coverage and evidence provenance."""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/science_fair_report_national_formatted.md"
VISUAL_DIR = ROOT / "docs/report_evidence_no_new_wet/comparison_visuals"
AUDIT_PATH = ROOT / "docs/report_evidence_no_new_wet/visual_audit.json"

REQUIRED_VISUALS = (
    "00_representative_sensor_curves_by_type.png",
    "01_initial_common_algorithm_mape.png",
    "02_selected_evaluator_by_type.png",
    "03_advanced_family_selection_map.png",
    "04_condition_method_ape_heatmap.png",
    "05_type_method_mape_heatmap.png",
    "06_comprehensive_method_mape.png",
    "07_comprehensive_method_mae_rmse.png",
    "08_tolerance_attainment.png",
    "09_manual_vs_final_condition_ape.png",
    "10_manual_signed_error.png",
    "11_nonml_vs_final_condition_ape.png",
    "12_unknown_repeatability_concentration.png",
    "13_repeatability_cv_comparison.png",
    "14_final_signed_error.png",
    "15_final_typewise_mae_rmse.png",
    "16_volume_group_mape.png",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def close(actual: float, expected: float, tolerance: float = 5e-6) -> bool:
    return math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance)


def metric_summary() -> dict:
    final_rows = read_csv(
        ROOT
        / "docs/report_evidence_no_new_wet/figures/source_data/01_02_condition_predictions.csv"
    )
    final_mape = sum(float(row["ape_percent"]) for row in final_rows) / len(final_rows)
    final_mae = sum(float(row["absolute_error_ml"]) for row in final_rows) / len(final_rows)
    final_rmse = math.sqrt(
        sum(float(row["absolute_error_ml"]) ** 2 for row in final_rows)
        / len(final_rows)
    )

    manual_rows = read_csv(ROOT / "data/report/manual_titration_results.csv")
    manual_errors = [
        float(row["manual_endpoint_ml"]) - float(row["reference_equivalence_ml"])
        for row in manual_rows
    ]
    manual_refs = [float(row["reference_equivalence_ml"]) for row in manual_rows]
    manual_mae = sum(abs(value) for value in manual_errors) / len(manual_errors)
    manual_rmse = math.sqrt(
        sum(value**2 for value in manual_errors) / len(manual_errors)
    )
    manual_mape = (
        sum(abs(error) / reference for error, reference in zip(manual_errors, manual_refs))
        / len(manual_errors)
        * 100.0
    )

    baseline = {
        row["method"]: row
        for row in read_csv(
            ROOT / "data/analysis/non_ml_baseline_comparison/overall_comparison.csv"
        )
    }
    repeatability = json.loads(
        (
            ROOT
            / "data/analysis/july_unknown_repeatability/july_unknown_repeatability_summary.json"
        ).read_text(encoding="utf-8")
    )

    return {
        "final_model": {
            "run_count": len(final_rows),
            "mae_ml": final_mae,
            "rmse_ml": final_rmse,
            "mape_percent": final_mape,
        },
        "manual_current": {
            "run_count": len(manual_rows),
            "mae_ml": manual_mae,
            "rmse_ml": manual_rmse,
            "mape_percent": manual_mape,
        },
        "non_ml": {
            "color_major_slope_mape_percent": float(
                baseline["color_major_slope"]["mape_percent"]
            ),
            "color_thermal_threshold_mape_percent": float(
                baseline["color_thermal_adaptive_threshold"]["mape_percent"]
            ),
        },
        "modality": {
            key: float(baseline[key]["mape_percent"])
            for key in (
                "machine_learning_color",
                "machine_learning_thermal",
                "machine_learning_fusion",
            )
        },
        "repeatability": repeatability["frozen_model_repeatability"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    report_text = REPORT.read_text(encoding="utf-8")

    image_links = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", report_text)
    for relative in image_links:
        path = REPORT.parent / relative
        if not path.is_file():
            errors.append(f"missing report image: {relative}")

    caption_numbers = [
        int(value) for value in re.findall(r"^\*\*그림 (\d+)\.", report_text, re.MULTILINE)
    ]
    list_numbers = [
        int(value) for value in re.findall(r"^\[그림 (\d+)\]", report_text, re.MULTILINE)
    ]
    expected_sequence = list(range(1, 24))
    if caption_numbers != expected_sequence:
        errors.append(f"figure captions are not 1..23: {caption_numbers}")
    if list_numbers != expected_sequence:
        errors.append(f"figure list is not 1..23: {list_numbers}")

    stale_tokens = (
        "poster_assets/ml_0",
        "nominal_vs_development.png",
        "development_relative_deviation.png",
        "endpoint_method_comparison.png",
    )
    for token in stale_tokens:
        if token in report_text:
            errors.append(f"stale visual reference remains: {token}")

    for name in REQUIRED_VISUALS:
        path = VISUAL_DIR / name
        if not path.is_file():
            errors.append(f"missing required comparison visual: {name}")
            continue
        with Image.open(path) as image:
            width, height = image.size
            dpi = image.info.get("dpi", (0.0, 0.0))
        if max(width, height) < 1800:
            errors.append(f"visual too small: {name} {width}x{height}")
        if min(dpi) < 250:
            warnings.append(f"PNG DPI metadata below 250: {name} {dpi}")
        source = VISUAL_DIR / "source_data" / f"{Path(name).stem}.csv"
        if not source.is_file():
            errors.append(f"missing visual source CSV: {source.relative_to(ROOT)}")

    if not (VISUAL_DIR / "README.md").is_file():
        errors.append("comparison visual README missing")

    metrics = metric_summary()
    expected_metrics = {
        ("final_model", "mae_ml"): 0.077543,
        ("final_model", "rmse_ml"): 0.090773,
        ("final_model", "mape_percent"): 0.295,
        ("manual_current", "mae_ml"): 0.6416666666666667,
        ("manual_current", "rmse_ml"): 0.75,
        ("manual_current", "mape_percent"): 2.0,
        ("non_ml", "color_major_slope_mape_percent"): 4.673611,
        ("non_ml", "color_thermal_threshold_mape_percent"): 5.645833,
        ("modality", "machine_learning_color"): 1.552056,
        ("modality", "machine_learning_thermal"): 3.661547,
        ("modality", "machine_learning_fusion"): 1.524496,
        ("repeatability", "cv_percent"): 0.9611503693940324,
    }
    for (group, field), expected in expected_metrics.items():
        actual = float(metrics[group][field])
        if not close(actual, expected):
            errors.append(
                f"metric mismatch {group}.{field}: actual={actual} expected={expected}"
            )

    required_report_tokens = (
        "2,030,370개 설정",
        "변동계수 0.96%",
        "RBF SVR",
        "pairwise ridge",
        "prototype",
        "독립 검증 정확도가 아닌",
    )
    for token in required_report_tokens:
        if token not in report_text:
            errors.append(f"required report evidence missing: {token}")

    result = {
        "status": "pass" if not errors else "fail",
        "strict": args.strict,
        "report_image_link_count": len(image_links),
        "figure_caption_count": len(caption_numbers),
        "required_comparison_visual_count": len(REQUIRED_VISUALS),
        "metrics": metrics,
        "errors": errors,
        "warnings": warnings,
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors and args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
