#!/usr/bin/env python3
"""Build the evidence-only supplemental bundle for the science-fair report.

The bundle intentionally keeps raw experiment files byte-for-byte unchanged,
labels the sensor-only 1.52% value as a selected retrospective development
result, and records unavailable or unconfirmed inputs instead of fabricating them.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import statistics
import zipfile
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PACKAGE_NAME = "전람회_최종추가자료"
OUT = DIST / PACKAGE_NAME
ZIP_PATH = DIST / f"{PACKAGE_NAME}.zip"
RAW_DIR = ROOT / "머신러닝용 파일모음"
FINAL_ML = ROOT / "data/ml/report_modality_sensor_features_only"
FINAL_NON_ML = ROOT / "data/analysis/non_ml_baseline_comparison"
FIGURES = ROOT / "docs/report_revision_figures"
IMAGE_ROOT = ROOT / "docs/report_images_organized"
EVIDENCE = ROOT / "data/analysis/report_evidence_no_new_wet"
EVIDENCE_DOCS = ROOT / "docs/report_evidence_no_new_wet"
CONSULTATION_PDF = ROOT / "[화학]서면컨설팅 보고서(4차)_1245_자격루에서 착안한 비접촉 스마트 자동 적정 장치.pdf"

TYPE_ORDER = [
    "strong_acid_strong_base",
    "strong_acid_weak_base",
    "weak_acid_strong_base",
    "weak_acid_weak_base",
]
TYPE_LABEL = {
    "strong_acid_strong_base": "강산-강염기",
    "strong_acid_weak_base": "강산-약염기",
    "weak_acid_strong_base": "약산-강염기",
    "weak_acid_weak_base": "약산-약염기",
}
TYPE_STEM = {
    "strong_acid_strong_base": "강산강염기",
    "strong_acid_weak_base": "강산약염기",
    "weak_acid_strong_base": "약산강염기",
    "weak_acid_weak_base": "약산약염기",
}
TYPE_COLOR = {
    "strong_acid_strong_base": "#2563EB",
    "strong_acid_weak_base": "#7C3AED",
    "weak_acid_strong_base": "#EA580C",
    "weak_acid_weak_base": "#059669",
}
CONCENTRATIONS = [0.10, 0.15, 0.20]

NAVY = "#172B4D"
BLUE = "#2563EB"
TEAL = "#059669"
ORANGE = "#EA580C"
RED = "#DC2626"
GRAY = "#64748B"
GRID = "#DCE3EC"


def setup_font() -> None:
    candidates = [
        Path.home() / ".local/share/fonts/Pretendard/Pretendard-Regular.ttf",
        Path("/mnt/c/Windows/Fonts/malgun.ttf"),
    ]
    family = "DejaVu Sans"
    for path in candidates:
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            family = font_manager.FontProperties(fname=str(path)).get_name()
            break
    plt.rcParams.update(
        {
            "font.family": family,
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": NAVY,
            "axes.labelcolor": NAVY,
            "text.color": NAVY,
            "xtick.color": NAVY,
            "ytick.color": NAVY,
            "font.size": 12,
            "axes.titlesize": 17,
            "axes.labelsize": 13,
            "legend.fontsize": 10,
            "savefig.dpi": 300,
        }
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_float(value: str | None) -> float:
    try:
        number = float(value) if value not in (None, "") else math.nan
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def minmax(values: np.ndarray) -> np.ndarray:
    finite = np.isfinite(values)
    out = np.full(values.shape, np.nan, dtype=float)
    if not finite.any():
        return out
    low = float(np.nanpercentile(values[finite], 1))
    high = float(np.nanpercentile(values[finite], 99))
    if high - low < 1e-12:
        out[finite] = 0.0
        return out
    out[finite] = np.clip((values[finite] - low) / (high - low), 0.0, 1.0)
    return out


def rolling_median(values: np.ndarray, window: int = 5) -> np.ndarray:
    if values.size == 0:
        return values
    result = np.full(values.shape, np.nan, dtype=float)
    radius = max(0, window // 2)
    for index in range(values.size):
        segment = values[max(0, index - radius) : min(values.size, index + radius + 1)]
        if np.isfinite(segment).any():
            result[index] = float(np.nanmedian(segment))
    return result


def style_axis(ax, grid_axis: str = "both") -> None:
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.8, alpha=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#94A3B8")
    ax.spines["bottom"].set_color("#94A3B8")


def save_figure(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", facecolor="white", dpi=300)
    plt.close(fig)


def copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_flat_files(source_dir: Path, destination_dir: Path) -> None:
    """Copy every regular file while preserving filenames."""
    for source in sorted(source_dir.iterdir()):
        if source.is_file():
            copy_file(source, destination_dir / source.name)


def prepare_output() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()


def inventory_raw_runs() -> tuple[dict[tuple[str, float], dict], list[dict]]:
    runs: dict[tuple[str, float], dict] = {}
    mapping: list[dict] = []
    for source in sorted(RAW_DIR.glob("*.csv")):
        rows = read_csv(source)
        if not rows:
            raise RuntimeError(f"empty raw CSV: {source}")
        first = rows[0]
        titration_type = first["titration_type"]
        concentration = round(float(first["sample_concentration_M"]), 2)
        key = (titration_type, concentration)
        if key in runs:
            raise RuntimeError(f"duplicate experiment condition: {key}")
        friendly = f"{TYPE_STEM[titration_type]}_{int(round(concentration * 100)):03d}.csv"
        target = OUT / "01_자동적정_원본CSV" / friendly
        copy_file(source, target)
        runs[key] = {
            "source": source,
            "target": target,
            "rows": rows,
            "theory": float(first["theoretical_equivalence_volume_ml"]),
            "indicator": first.get("indicator", ""),
        }
        mapping.append(
            {
                "정리파일명": friendly,
                "원본파일명": source.name,
                "적정종류": TYPE_LABEL[titration_type],
                "농도_M": f"{concentration:.2f}",
                "행수": len(rows),
                "지시약_CSV메타데이터": first.get("indicator", ""),
                "연구수행자_사후확인값": (
                    "bromothymol_blue (BTB)"
                    if titration_type == "weak_acid_weak_base"
                    else first.get("indicator", "")
                ),
                "메타데이터상태": (
                    "원본과 사후 확인이 상충함; run-linked 1차 기록 미확보"
                    if titration_type == "weak_acid_weak_base"
                    else "원본 기록과 실제 조건 일치"
                ),
                "정정검증상태": (
                    "연구 수행자 사후 확인; 독립 검증되지 않음"
                    if titration_type == "weak_acid_weak_base"
                    else "해당 없음"
                ),
                "SHA256": sha256(source),
            }
        )
    if len(runs) != 12 or sum(len(item["rows"]) for item in runs.values()) != 1822:
        raise RuntimeError("expected exactly 12 runs and 1,822 raw rows")
    write_csv(
        OUT / "01_자동적정_원본CSV/원본CSV_매핑.csv",
        mapping,
        [
            "정리파일명",
            "원본파일명",
            "적정종류",
            "농도_M",
            "행수",
            "지시약_CSV메타데이터",
            "연구수행자_사후확인값",
            "메타데이터상태",
            "정정검증상태",
            "SHA256",
        ],
    )
    return runs, mapping


def smart_comparison_rows() -> list[dict[str, str]]:
    rows = read_csv(FIGURES / "source_data/smart_manual_run_comparison.csv")
    if len(rows) != 12:
        raise RuntimeError("expected 12 smart/manual comparison rows")
    return rows


def copy_analysis_materials() -> None:
    base = OUT / "02_최종분석코드"
    ml_code = base / "머신러닝/코드"
    ml_results = base / "머신러닝/최종결과_센서전용_1점52퍼센트"
    nonml = base / "비머신러닝"
    autostop = base / "자동정지"
    settings = base / "설정파일"
    results = base / "결과파일"
    evidence = base / "기존12회_엄밀성재분석"
    pulse = base / "종말점근처_펄스제어_건식시험"

    for relative in [
        "tools/report_modality_development_selector.py",
        "auto_titrator/ml_curve_equivalence.py",
        "auto_titrator/ml_features.py",
        "auto_titrator/ml_model_zoo_equivalence.py",
        "auto_titrator/ml_train.py",
        "auto_titrator/ml_predict.py",
        "auto_titrator/ml_typewise_eval.py",
        "auto_titrator/evaluation.py",
        "auto_titrator/data_schema.py",
    ]:
        copy_file(ROOT / relative, ml_code / relative)
    for source in sorted(FINAL_ML.iterdir()):
        if source.is_file():
            copy_file(source, ml_results / source.name)

    copy_file(ROOT / "tools/compare_endpoint_baselines.py", nonml / "compare_endpoint_baselines.py")
    copy_file(FINAL_NON_ML / "per_run_predictions.csv", nonml / "per_run_predictions.csv")
    original_summary = json.loads((FINAL_NON_ML / "summary.json").read_text(encoding="utf-8"))
    baseline_summary = {
        "schema_version": "report_baselines_only_v1",
        "selection_scope": original_summary["selection_scope"],
        "run_count": original_summary["run_count"],
        "rules": original_summary["rules"],
        "comparison": [
            row
            for row in original_summary["comparison"]
            if row["method"] in {"color_major_slope", "color_thermal_adaptive_threshold"}
        ],
        "note": "오래된 수동 1.215% 행과 주입량 포함 1.27% 모델은 최종 보고서 자료에서 제외함.",
    }
    write_text(nonml / "설정및최종결과.json", json.dumps(baseline_summary, ensure_ascii=False, indent=2))

    for relative in [
        "auto_titrator/auto_stop.py",
        "tests/test_auto_stop.py",
        "docs/AUTO_STOP_VALIDATION.md",
    ]:
        copy_file(ROOT / relative, autostop / Path(relative).name)

    for relative in [
        "tools/analyze_existing_data_report_evidence.py",
        "tests/test_existing_data_report_analysis.py",
        "tools/validate_existing_data_report_evidence.py",
        "tests/test_validate_existing_data_report_evidence.py",
    ]:
        copy_file(ROOT / relative, evidence / Path(relative).name)
    for source in sorted(EVIDENCE.iterdir()):
        if source.is_file():
            copy_file(source, evidence / "산출물" / source.name)

    for relative in [
        "auto_titrator/pulse_control.py",
        "tests/test_pulse_control.py",
    ]:
        copy_file(ROOT / relative, pulse / Path(relative).name)
    write_text(
        pulse / "해석주의.txt",
        """
이 폴더의 펄스 제어는 software-only, dry-tested 상태기계와 단위시험이다.
기존 12회 습식 실험에 적용하지 않았으며, 실제 펌프 펌웨어 통합·펄스별 토출량·정지 지연·정밀도 향상을 검증하지 않았다.
""",
    )

    report_patch = OUT / "10_4차컨설팅_반영문안"
    for name in (
        "보고서_교체문안.md",
        "표_및_그림_캡션.md",
        "claim_source_manifest.csv",
        "4차컨설팅_반영요약.md",
        "participant_indicator_correction_record.md",
    ):
        copy_file(EVIDENCE_DOCS / name, report_patch / name)
    for name in (
        "paired_endpoint_errors.png",
        "thermal_contrast_by_run.png",
        "thermal_contrast_vs_fusion_improvement.png",
    ):
        copy_file(EVIDENCE / name, OUT / "04_그래프" / name)

    for relative in [
        "auto_titrator/config.yaml",
        "auto_titrator/chemical_constants.py",
        "requirements.txt",
    ]:
        copy_file(ROOT / relative, settings / Path(relative).name)

    copy_file(FIGURES / "source_data/method_comparison.csv", results / "최종_판정방식별_성능.csv")
    copy_file(FIGURES / "source_data/smart_manual_run_comparison.csv", results / "자동_수동_12조건_비교.csv")
    copy_file(ROOT / "data/report/manual_titration_results.csv", results / "수동적정_12회_결과.csv")

    write_text(
        base / "재현방법과해석주의.txt",
        """
[최종 머신러닝 결과]
- 센서 입력만 사용한 색상+열화상 융합 MAPE: 1.524496% (보고서 표기 1.52%)
- 색상 전용 MAPE: 1.552056%
- 열화상 전용 MAPE: 3.661547%
- 현재 주입량, 시료 농도, 이론 당량점, 진행률·종료 정보는 모델 특징에서 제외하였다.

[묶음 루트에서 재현·검증]
python3 tools/analyze_existing_data_report_evidence.py --output-dir reproduced/report_evidence_no_new_wet
python3 tools/validate_existing_data_report_evidence.py --json
python3 -m unittest -v tests.test_existing_data_report_analysis tests.test_validate_existing_data_report_evidence tests.test_pulse_control

첫 명령은 원본 12회와 저장된 예측 파일에서 재분석 산출물을 새 폴더에 만든다. 두 번째 명령은 배포 묶음 안의 원본 해시·행수·수치·주장 출처를 검증한다.

[평가 범위]
12개 run을 leave-one-run-out 방식으로 분리했지만, 적정 종류별 방법 선택은 같은 12개 개발자료에서 사후 선택했다. 따라서 독립 최종 검증 또는 nested 검증 결과로 표현하면 안 된다.
색상 대비 융합의 1차 짝지은 비교는 APE 차이이며, 반응계 층화 run-level bootstrap 구간이 0을 포함한다. 1.52%를 열화상 우월성의 증거로 쓰지 않는다.

[비머신러닝]
색 최대 기울기 MAPE 4.673611%, 색·온도 적응 임계값 MAPE 5.645833%이다. 세부 임계값·가중치·평활화 폭은 비머신러닝/설정및최종결과.json에 있다.

[자동정지]
모델 점수 기준 0.30, 색 변화 지속 확인 0.4초를 사용한다. 기존 12회는 사람이 정지한 습식 실험이므로 자동정지 정확도의 독립 검증으로 표현하지 않는다.
""",
    )


def copy_reproducible_repository_layout() -> None:
    """Bundle a minimal repository-relative tree that validates from package root."""
    copy_flat_files(RAW_DIR, OUT / "머신러닝용 파일모음")
    copy_flat_files(EVIDENCE, OUT / "data/analysis/report_evidence_no_new_wet")
    copy_flat_files(FINAL_ML, OUT / "data/ml/report_modality_sensor_features_only")

    exact_files = [
        "tools/analyze_existing_data_report_evidence.py",
        "tools/validate_existing_data_report_evidence.py",
        "tests/__init__.py",
        "tests/test_existing_data_report_analysis.py",
        "tests/test_validate_existing_data_report_evidence.py",
        "tests/test_pulse_control.py",
        "auto_titrator/__init__.py",
        "auto_titrator/pulse_control.py",
        "auto_titrator/pump_controller.py",
        "docs/report_revision_figures/source_data/method_comparison.csv",
        "data/report/manual_titration_results.csv",
        "requirements.txt",
    ]
    for relative in exact_files:
        copy_file(ROOT / relative, OUT / relative)

    for name in (
        "보고서_교체문안.md",
        "표_및_그림_캡션.md",
        "claim_source_manifest.csv",
        "4차컨설팅_반영요약.md",
        "participant_indicator_correction_record.md",
    ):
        copy_file(EVIDENCE_DOCS / name, OUT / "docs/report_evidence_no_new_wet" / name)
    copy_file(CONSULTATION_PDF, OUT / CONSULTATION_PDF.name)

    write_text(
        OUT / "재현_및_검증.txt",
        """
[실행 위치]
이 파일이 있는 전람회_최종추가자료 폴더를 현재 작업 폴더로 둔다.

[기존 12회 엄밀성 재분석]
python3 tools/analyze_existing_data_report_evidence.py --output-dir reproduced/report_evidence_no_new_wet

[배포 묶음 무결성·근거 검증]
python3 tools/validate_existing_data_report_evidence.py --json

[추가 코드 단위시험]
python3 -m unittest -v tests.test_existing_data_report_analysis tests.test_validate_existing_data_report_evidence tests.test_pulse_control

재분석은 새 습식 실험이나 독립 검증이 아니다. 저장된 12회 원본과 저장된 모델 예측을 다시 계산하는 절차이다.
""",
    )


def prediction_map(rows: list[dict[str, str]]) -> dict[tuple[str, float], float]:
    return {
        (row["titration_type"], round(float(row["concentration_M"]), 2)): float(
            row["smart_predicted_ml"]
        )
        for row in rows
    }


def graph_hsv_by_type(runs: dict[tuple[str, float], dict]) -> None:
    out = OUT / "05_원자료그래프"
    for titration_type in TYPE_ORDER:
        fig, axes = plt.subplots(3, 1, figsize=(12, 11), sharex=False)
        for ax, concentration in zip(axes, CONCENTRATIONS):
            run = runs[(titration_type, concentration)]
            rows = run["rows"]
            x = np.array([safe_float(row.get("injected_volume_ml")) for row in rows])
            series = {
                "H": np.array([safe_float(row.get("visible_H_mean")) for row in rows]),
                "S": np.array([safe_float(row.get("visible_S_mean")) for row in rows]),
                "V": np.array([safe_float(row.get("visible_V_mean")) for row in rows]),
            }
            for label, color in [("H", "#7C3AED"), ("S", "#EA580C"), ("V", "#059669")]:
                y = rolling_median(minmax(series[label]), 5)
                ax.plot(x, y, color=color, linewidth=1.8, label=f"{label} 정규화값")
            ax.axvline(run["theory"], color=NAVY, linestyle="--", linewidth=1.5, label="이론 당량점")
            ax.set_ylim(-0.04, 1.04)
            ax.set_ylabel("정규화값")
            ax.set_title(f"{concentration:.2f} M · 이론 당량점 {run['theory']:.1f} mL", loc="left", fontsize=13, fontweight="bold")
            style_axis(ax)
        axes[0].legend(frameon=False, ncol=4, loc="upper right")
        axes[-1].set_xlabel("적정액 주입량 (mL)")
        fig.suptitle(
            f"{TYPE_LABEL[titration_type]}: 농도별 HSV 원자료 변화",
            x=0.08,
            ha="left",
            fontsize=20,
            fontweight="bold",
        )
        fig.text(0.08, 0.015, "H·S·V는 각 실험의 관측 범위로 0~1 정규화하고 5점 중앙값을 적용해 표시함.", color=GRAY, fontsize=10)
        fig.tight_layout(rect=(0.04, 0.04, 0.98, 0.95))
        save_figure(fig, out / f"{TYPE_STEM[titration_type]}_HSV.png")


def graph_color_thermal_by_type(
    runs: dict[tuple[str, float], dict], comparison: list[dict[str, str]]
) -> None:
    out = OUT / "05_원자료그래프"
    predictions = prediction_map(comparison)
    for titration_type in TYPE_ORDER:
        fig, axes = plt.subplots(3, 1, figsize=(12, 11), sharex=False)
        for ax, concentration in zip(axes, CONCENTRATIONS):
            run = runs[(titration_type, concentration)]
            rows = run["rows"]
            x = np.array([safe_float(row.get("injected_volume_ml")) for row in rows])
            color_raw = np.array([safe_float(row.get("visible_color_delta")) for row in rows])
            thermal_raw = np.array([safe_float(row.get("thermal_roi_avg")) for row in rows])
            finite_thermal = thermal_raw[np.isfinite(thermal_raw)]
            baseline_count = max(3, int(finite_thermal.size * 0.10))
            baseline = float(np.nanmedian(finite_thermal[:baseline_count])) if finite_thermal.size else math.nan
            thermal_change = np.abs(thermal_raw - baseline)
            ax.plot(x, rolling_median(minmax(color_raw), 5), color=BLUE, linewidth=2.0, label="색 변화")
            ax.plot(x, rolling_median(minmax(thermal_change), 5), color=ORANGE, linewidth=2.0, label="열 변화")
            ax.axvline(run["theory"], color=NAVY, linestyle="--", linewidth=1.5, label="이론 당량점")
            ax.axvline(predictions[(titration_type, concentration)], color=RED, linestyle="-", linewidth=1.4, label="융합 모델 추정")
            ax.set_ylim(-0.04, 1.04)
            ax.set_ylabel("정규화 변화량")
            ax.set_title(f"{concentration:.2f} M", loc="left", fontsize=13, fontweight="bold")
            style_axis(ax)
        axes[0].legend(frameon=False, ncol=4, loc="upper right")
        axes[-1].set_xlabel("적정액 주입량 (mL)")
        fig.suptitle(
            f"{TYPE_LABEL[titration_type]}: 색상·열화상 변화와 당량점",
            x=0.08,
            ha="left",
            fontsize=20,
            fontweight="bold",
        )
        fig.text(0.08, 0.015, "색 변화량과 초기 온도 대비 변화량을 각각 0~1 정규화하고 5점 중앙값을 적용해 표시함.", color=GRAY, fontsize=10)
        fig.tight_layout(rect=(0.04, 0.04, 0.98, 0.95))
        save_figure(fig, out / f"{TYPE_STEM[titration_type]}_색열.png")


def graph_time_volume() -> None:
    t = np.linspace(0, 45, 181)
    v = 0.99 * t
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(t, v, color=BLUE, linewidth=3)
    for seconds in (10, 20, 30, 40):
        ax.scatter([seconds], [0.99 * seconds], s=55, color=TEAL, zorder=3)
        ax.annotate(f"{0.99 * seconds:.1f} mL", (seconds, 0.99 * seconds), xytext=(5, 8), textcoords="offset points", fontsize=10)
    ax.set_xlabel("펌프 작동 시간 t (s)")
    ax.set_ylabel("계산 누적 주입량 V (mL)")
    ax.set_title("펌프 작동 시간과 계산 누적 주입량", loc="left", fontweight="bold")
    ax.text(0.04, 0.90, "V = 0.99t", transform=ax.transAxes, fontsize=22, fontweight="bold", color=TEAL)
    ax.text(0.04, 0.82, "계산 원리 도식(반복 유량 실측 그래프가 아님)", transform=ax.transAxes, color=GRAY)
    style_axis(ax)
    save_figure(fig, OUT / "03_유량보정/시간_누적주입량_계산원리.png")


def graph_additional_performance(comparison: list[dict[str, str]]) -> None:
    out = OUT / "04_그래프"
    theory = np.array([float(row["theoretical_ml"]) for row in comparison])
    smart = np.array([float(row["smart_predicted_ml"]) for row in comparison])
    manual = np.array([float(row["manual_endpoint_ml"]) for row in comparison])

    fig, ax = plt.subplots(figsize=(8, 7))
    for titration_type in TYPE_ORDER:
        selected = [row for row in comparison if row["titration_type"] == titration_type]
        ax.scatter(
            [float(row["theoretical_ml"]) for row in selected],
            [float(row["smart_predicted_ml"]) for row in selected],
            s=95,
            color=TYPE_COLOR[titration_type],
            edgecolor="white",
            linewidth=1.2,
            label=TYPE_LABEL[titration_type],
        )
    bounds = (18, 42)
    ax.plot(bounds, bounds, linestyle="--", color=NAVY, linewidth=1.5, label="y=x")
    ax.set_xlim(bounds)
    ax.set_ylim(bounds)
    ax.set_xlabel("이론 당량점 (mL)")
    ax.set_ylabel("자동 추정 당량점 (mL)")
    ax.set_title("이론 당량점과 자동 추정 당량점", loc="left", fontweight="bold")
    ax.legend(frameon=False, ncol=2)
    style_axis(ax)
    save_figure(fig, out / "자동적정_이론값_추정값_산점도.png")

    type_rows = []
    for titration_type in TYPE_ORDER:
        selected = [row for row in comparison if row["titration_type"] == titration_type]
        auto_mape = statistics.mean(float(row["smart_abs_percentage_error"]) for row in selected)
        manual_mape = statistics.mean(float(row["manual_abs_percentage_error"]) for row in selected)
        type_rows.append((TYPE_LABEL[titration_type], auto_mape, manual_mape))
    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(type_rows))
    width = 0.36
    auto_bars = ax.bar(x - width / 2, [r[1] for r in type_rows], width, color=TEAL, label="자동 적정")
    manual_bars = ax.bar(x + width / 2, [r[2] for r in type_rows], width, color=GRAY, label="수동 적정")
    for bars in (auto_bars, manual_bars):
        for bar in bars:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.08, f"{bar.get_height():.2f}%", ha="center", va="bottom", fontsize=10)
    ax.axhline(5, color=RED, linestyle="--", linewidth=1.2, label="5% 기준")
    ax.set_xticks(x, [r[0] for r in type_rows])
    ax.set_ylabel("MAPE (%)")
    ax.set_title("반응계별 수동·자동 적정 MAPE", loc="left", fontweight="bold")
    ax.legend(frameon=False, ncol=3)
    ax.set_ylim(0, 5.6)
    style_axis(ax, "y")
    save_figure(fig, out / "반응계별_수동자동_MAPE.png")

    def metric(actual: np.ndarray, pred: np.ndarray) -> tuple[float, float, float]:
        err = pred - actual
        return (
            float(np.mean(np.abs(err))),
            float(np.sqrt(np.mean(err**2))),
            float(np.mean(np.abs(err) / actual) * 100.0),
        )

    smart_metrics = metric(theory, smart)
    manual_metrics = metric(theory, manual)
    fig, ax = plt.subplots(figsize=(8, 6))
    x = np.arange(2)
    width = 0.34
    b1 = ax.bar(x - width / 2, [manual_metrics[0], smart_metrics[0]], width, color=BLUE, label="MAE")
    b2 = ax.bar(x + width / 2, [manual_metrics[1], smart_metrics[1]], width, color=ORANGE, label="RMSE")
    for bars in (b1, b2):
        for bar in bars:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.025, f"{bar.get_height():.2f}", ha="center", fontsize=11)
    ax.set_xticks(x, ["수동 적정", "자동 적정"])
    ax.set_ylabel("부피 오차 (mL)")
    ax.set_title("수동·자동 적정 전체 MAE와 RMSE", loc="left", fontweight="bold")
    ax.legend(frameon=False, ncol=2)
    ax.set_ylim(0, 1.0)
    style_axis(ax, "y")
    save_figure(fig, out / "수동자동_전체성능_MAE_RMSE.png")

    fig, ax = plt.subplots(figsize=(7, 6))
    bars = ax.bar(["수동 적정", "자동 적정"], [manual_metrics[2], smart_metrics[2]], color=[GRAY, TEAL], width=0.58)
    for bar in bars:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05, f"{bar.get_height():.2f}%", ha="center", fontsize=12, fontweight="bold")
    ax.set_ylabel("MAPE (%)")
    ax.set_title("수동·자동 적정 전체 MAPE", loc="left", fontweight="bold")
    ax.set_ylim(0, 2.5)
    style_axis(ax, "y")
    save_figure(fig, out / "수동자동_전체성능_MAPE.png")


def copy_existing_graphs() -> None:
    destination = OUT / "04_그래프"
    graph_map = {
        "01_smart_theory_vs_prediction.png": "자동적정_이론값_추정값.png",
        "02_smart_error_by_condition.png": "자동적정_조건별오차율.png",
        "03_manual_vs_smart_by_condition.png": "수동자동_조건별오차율.png",
        "04_method_comparison_mape.png": "판정방식별_MAPE.png",
        "05_method_comparison_mae_rmse.png": "판정방식별_MAE_RMSE.png",
        "06_sensor_modality_comparison.png": "센서입력군별_성능.png",
        "07_fusion_typewise_mape.png": "자동적정_적정종류별_MAPE.png",
        "10_manual_theory_vs_endpoint.png": "수동적정_기준값_종말점.png",
        "11_manual_signed_error.png": "수동적정_조건별_부호오차.png",
    }
    for source, target in graph_map.items():
        copy_file(FIGURES / source, destination / target)
    source_dir = destination / "그래프_원본수치"
    for source in sorted((FIGURES / "source_data").glob("*.csv")):
        copy_file(source, source_dir / source.name)
    copy_file(FIGURES / "README.md", destination / "그래프_설명.txt")

    optional = OUT / "99_조건확인필요/반복성"
    copy_file(FIGURES / "08_repeatability_three_runs.png", optional / "동일용액_3회_반복측정_조건확인필요.png")
    write_text(
        optional / "사용전확인.txt",
        "0.0824, 0.0851, 0.0889 M의 시료·농도·적정액·지시약 조건이 확인되지 않았다. 조건을 확인하기 전에는 본문 증거로 사용하지 않는다.",
    )


def normalize_report_png_dpi() -> None:
    """Set print-resolution metadata consistently without changing pixel size."""
    folders = [
        OUT / "03_유량보정",
        OUT / "04_그래프",
        OUT / "05_원자료그래프",
        OUT / "07_도식",
        OUT / "99_조건확인필요/반복성",
    ]
    for folder in folders:
        for path in sorted(folder.glob("*.png")):
            with Image.open(path) as image:
                image.load()
                copy = image.copy()
            temporary = path.with_suffix(".tmp.png")
            copy.save(temporary, format="PNG", dpi=(300, 300), optimize=True)
            temporary.replace(path)


def copy_photos() -> None:
    base = OUT / "06_사진원본"
    photo_map = [
        ("01_system_experiment/01_system_overview_three_views.png", "전체장치/전체장치_세방향.png", "실제사진"),
        ("01_system_experiment/08_completed_syringe_pump.png", "펌프/완성_시린지펌프.png", "실제사진"),
        ("02_hardware_design/02_syringe_pump_parts_overview.png", "펌프/시린지펌프_부품구성.png", "구성도"),
        ("02_hardware_design/03_pump_3d_models_overview.png", "펌프/시린지펌프_3D모델.png", "3D모델"),
        ("02_hardware_design/04_pusher_block_3d_model.png", "펌프/푸셔블록_3D모델.png", "3D모델"),
        ("02_hardware_design/05_motor_holder_rail_3d_model.png", "펌프/모터홀더_가이드_3D모델.png", "3D모델"),
        ("02_hardware_design/07_arduino_a4988_stepper_circuit.png", "회로/Arduino_A4988_회로도.png", "회로도"),
        ("01_system_experiment/12_phenolphthalein_titration_setup.png", "수동적정/페놀프탈레인_적정장면.png", "실제사진"),
        ("01_system_experiment/13_btb_color_change_setup.png", "수동적정/BTB_적정장면.png", "실제사진"),
        ("06_additional_created_assets/wet_titration_setup.jpg", "자동적정/습식적정_장치사진.jpg", "실제사진"),
        ("01_system_experiment/11_four_reagent_solutions.png", "지시약변화/시약용액_전체.png", "실제사진"),
        ("03_software_ui/09_windows_dashboard_full.png", "Windows앱/Windows_전체대시보드.png", "실행화면"),
        ("03_software_ui/10_windows_android_comparison.png", "Android앱/Windows_Android_비교화면.png", "실행화면"),
    ]
    inventory: list[dict] = []
    for relative, target, kind in photo_map:
        source = IMAGE_ROOT / relative
        destination = base / target
        copy_file(source, destination)
        with Image.open(source) as image:
            width, height = image.size
        inventory.append(
            {
                "분류": target.split("/")[0],
                "파일명": Path(target).name,
                "자료형": kind,
                "가로_px": width,
                "세로_px": height,
                "원본경로": str(source.relative_to(ROOT)),
                "SHA256": sha256(source),
            }
        )
    write_csv(
        base / "사진목록.csv",
        inventory,
        ["분류", "파일명", "자료형", "가로_px", "세로_px", "원본경로", "SHA256"],
    )
    write_text(base / "유량보정/촬영필요.txt", "10 mL 토출량과 시간을 함께 확인할 수 있는 유량 보정 원본 사진이 발견되지 않았다.")
    write_text(base / "자동정지/실행화면_촬영필요.txt", "자동정지 실제 실행 화면은 확보되지 않았다. 프로그램 상태도는 07_도식에 수록했다.")
    write_text(base / "Android앱/주의.txt", "독립 Android 원본 화면이 없어 Windows·Android 비교 합성 화면을 수록했다.")


def draw_box(ax, x: float, y: float, text: str, color: str, width: float = 0.25, height: float = 0.15) -> None:
    from matplotlib.patches import FancyBboxPatch

    patch = FancyBboxPatch(
        (x - width / 2, y - height / 2),
        width,
        height,
        boxstyle="round,pad=0.012,rounding_size=0.02",
        linewidth=1.5,
        edgecolor=color,
        facecolor=color + "18",
    )
    ax.add_patch(patch)
    ax.text(x, y, text, ha="center", va="center", fontsize=12, fontweight="bold", color=NAVY)


def graph_jagyeokru_comparison() -> None:
    fig, ax = plt.subplots(figsize=(12, 6.5))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.05, 0.93, "자격루와 비접촉 스마트 자동 적정 장치의 원리 비교", fontsize=21, fontweight="bold")
    rows = [
        ("자격루", 0.68, ["일정한 물의 흐름", "이동한 물의 양 측정", "경과 시간 계산", "시각 알림"], BLUE),
        ("본 장치", 0.31, ["일정한 모터 작동", "작동 시간 측정", "적정액 양 계산", "당량점 표시·정지 명령"], TEAL),
    ]
    xs = [0.21, 0.43, 0.65, 0.87]
    for name, y, labels, color in rows:
        ax.text(0.04, y, name, ha="left", va="center", fontsize=16, fontweight="bold", color=color)
        for index, (x, label) in enumerate(zip(xs, labels)):
            draw_box(ax, x, y, label, color, width=0.18, height=0.16)
            if index < len(xs) - 1:
                ax.annotate("", xy=(xs[index + 1] - 0.105, y), xytext=(x + 0.105, y), arrowprops={"arrowstyle": "->", "color": GRAY, "lw": 1.8})
    ax.text(0.05, 0.08, "공통 원리: 일정한 흐름에서 시간과 이동한 액체량을 연결하여 상태를 판정한다.", fontsize=13, color=GRAY)
    save_figure(fig, OUT / "07_도식/자격루_장치_원리비교.png")


def copy_diagrams() -> None:
    source = ROOT / "docs/report_assets"
    mapping = {
        "research_flow.png": "연구흐름도.png",
        "system_data_flow.png": "전체시스템구성도.png",
        "auto_stop_state_machine.png": "자동정지흐름도.png",
    }
    for original, target in mapping.items():
        copy_file(source / original, OUT / "07_도식" / target)
    graph_jagyeokru_comparison()


def write_calibration_and_information() -> None:
    write_text(
        OUT / "03_유량보정/유량보정원자료_입력필요.txt",
        """
측정 액체:
측정 기구:
토출 목표 부피: 10 mL

1회 토출 시간:
2회 토출 시간:
3회 토출 시간:
4회 토출 시간:
5회 토출 시간:
추가 반복:

평균 유량 0.99 mL/s를 계산한 실제 방식:
""",
    )
    write_text(
        OUT / "08_실험정보.txt",
        """
[실제 실험 조건]
일반 카메라 거리:
열화상 카메라 거리:
일반 카메라 모델:
일반 카메라 해상도:
실제 습식 실험 촬영 속도:
소프트웨어 CSV 처리 경로 시험: 25.0행/s(0.04초 간격 시험 입력). 실제 습식 실험 촬영 속도와 구분할 것.
교반 속도:
조명:
배경:
지시약 투입량:
호스 길이:
실내 온도:

[반복성 실험 — 본문에 유지할 때만 입력]
적정 종류:
시료:
농도:
부피:
적정액:
농도:
지시약:
세 번 모두 같은 조제 용액인지:
0.0824, 0.0851, 0.0889 M는 앱이 계산한 시료 농도인지:

[수동·자동 비교]
같은 날 여부:
같은 조제 용액 여부:
시료 부피 동일 여부:
적정액 농도 동일 여부:
지시약 동일 여부:

[열화상 이상값]
0값·결측값 처리 방법:

[머신러닝]
최종 결과: 센서 전용 색상+열화상 융합 MAPE 1.524496%(보고서 1.52%)
정답 구간·평활화·이동 창·모델 설정: 02_최종분석코드/머신러닝/최종결과_센서전용_1점52퍼센트/report.md 및 summary.json 참조
제외 입력: 현재 주입량, 시료 농도, 이론 당량점, 진행률, 종료 정보
평가 주의: 같은 12개 개발자료에서 적정 종류별 방법을 사후 선택했으므로 독립 최종 검증으로 표현하지 않음.

[지시약 메타데이터 확인]
약산-약염기 3회는 연구 수행자의 사후 확인상 BTB이다. 다만 원본 CSV에는 methyl_orange로 기록되어 있고, 당시 run과 직접 연결되는 1차 기록을 현재 자료에서 찾지 못했다. 따라서 원본은 변경하지 않고, 원본CSV_매핑.csv에는 BTB를 미독립검증 사후 정정으로 표시했다.
""",
    )


def write_readme_and_missing(mapping: list[dict]) -> None:
    write_text(
        OUT / "00_읽어주세요.txt",
        f"""
이 묶음은 최종 보고서 작성에 필요한 기존 자료를 한곳에 정리한 것이다.

[검증된 핵심]
- 자동 적정 원본 CSV: 12개, 총 {sum(int(row['행수']) for row in mapping):,}행
- 센서 전용 색상+열화상 융합 모델의 사후 개발 MAPE: 1.524496%(1.52%); 독립 검증값이 아님
- 색상 전용 ML: 1.552056%(1.55%), 열화상 전용 ML: 3.661547%(3.66%)
- 비머신러닝 색 최대 기울기: 4.673611%(4.67%)
- 비머신러닝 색·온도 임계값: 5.645833%(5.65%)
- 최종 수동 적정 12회: MAE 0.642 mL, RMSE 0.750 mL, MAPE 2.00%

[자료 선택 원칙]
- 원본 CSV는 내용 변경 없이 파일명만 알아보기 쉽게 복사했다. 원본명·행수·해시는 원본CSV_매핑.csv에 있다.
- 현재 주입량을 특징으로 사용한 과거 1.27% 모델과 오래된 수동 1.215% 결과는 제외했다.
- 오래된 보고서·HWPX·APK·HIKMICRO 바이너리·캐시·.omx 자료는 포함하지 않았다.
- 반복성 그래프는 실험 조건이 확인되지 않아 99_조건확인필요에 분리했다.
- 반복 유량 실측값과 일부 촬영 조건은 찾지 못했으며 입력 양식만 제공했다.

[중요 불일치]
약산-약염기 3회는 연구 수행자의 사후 확인상 BTB이지만 원본 CSV에는 indicator=methyl_orange로 기록되어 있다. 당시 run과 직접 연결되는 실험일지·시약 사진을 현재 자료에서 찾지 못했으므로, BTB는 미독립검증 사후 정정으로만 표시한다. 원본 CSV는 수정하지 않았다.

[재현 가능 구조]
보기 편한 한글 폴더와 별도로, 묶음 루트에 원본 파일명과 repository-relative 경로를 보존한 최소 재현 트리를 함께 넣었다. `재현_및_검증.txt`의 명령을 묶음 루트에서 실행하면 재분석·검증·단위시험을 수행할 수 있다.

[그래프]
기존 최종 그래프와 원본 수치를 04_그래프에 넣었다. 반응계별 HSV·색/열 원자료 그래프는 05_원자료그래프에 새로 생성했다. 모든 새 그래프는 PNG 300 dpi이며 가로 1,800 px 이상이다.
""",
    )
    write_text(
        OUT / "09_누락자료_체크리스트.txt",
        """
[반드시 사람이 확인·추가해야 하는 자료]
□ 10 mL 반복 토출 시간 원자료와 유량 보정 실제 사진
□ 일반 카메라 거리·모델·해상도·실제 습식 촬영 속도
□ 열화상 카메라 거리, 조명, 배경, 교반 속도, 지시약 투입량, 호스 길이, 실내 온도
□ 수동·자동 적정이 같은 날·같은 조제 용액·같은 조건이었는지
□ 열화상 0값·결측값 처리 방법
□ 반복성 0.0824·0.0851·0.0889 M의 시료·적정액·지시약 조건
□ 실제 자동정지 실행 화면 또는 습식 반복 시험(본문에서 실증 주장할 때만)
□ 독립 Android 앱 원본 화면 및 전용 열화상 ROI 화면(현재는 비교 합성 화면만 있음)

[현재 자료만으로 쓰면 안 되는 주장]
- 1.52%를 독립 최종 검증 정확도라고 단정
- 기존 12회가 자동정지 성능을 검증했다고 단정
- 25행/s 처리 경로 시험을 실제 습식 촬영 속도라고 단정
- 유량 반복값 없이 0.99 mL/s의 표준편차·재현성을 제시
""",
    )


def validate_images() -> list[dict]:
    results = []
    for path in sorted((OUT / "04_그래프").glob("*.png")) + sorted((OUT / "05_원자료그래프").glob("*.png")) + sorted((OUT / "07_도식").glob("*.png")):
        with Image.open(path) as image:
            width, height = image.size
            dpi = image.info.get("dpi")
        results.append({"file": str(path.relative_to(OUT)), "width": width, "height": height, "dpi": dpi})
        if path.parent.name in {"04_그래프", "05_원자료그래프", "07_도식"} and width < 1800:
            raise RuntimeError(f"report graph narrower than 1800 px: {path} ({width})")
        if not dpi or min(float(dpi[0]), float(dpi[1])) < 299:
            raise RuntimeError(f"report graph is not tagged at 300 dpi: {path} ({dpi})")
    return results


def write_hashes() -> None:
    lines = []
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            lines.append(f"{sha256(path)}  {path.relative_to(OUT).as_posix()}")
    write_text(OUT / "SHA256SUMS.txt", "\n".join(lines))


def create_zip() -> None:
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(OUT.rglob("*")):
            if path.is_file():
                archive.write(path, Path(PACKAGE_NAME) / path.relative_to(OUT))


def main() -> int:
    setup_font()
    prepare_output()
    runs, mapping = inventory_raw_runs()
    comparison = smart_comparison_rows()
    copy_analysis_materials()
    copy_existing_graphs()
    graph_hsv_by_type(runs)
    graph_color_thermal_by_type(runs, comparison)
    graph_time_volume()
    graph_additional_performance(comparison)
    copy_photos()
    copy_diagrams()
    write_calibration_and_information()
    write_readme_and_missing(mapping)
    copy_reproducible_repository_layout()
    normalize_report_png_dpi()
    image_validation = validate_images()
    write_text(OUT / "그래프_검증.json", json.dumps(image_validation, ensure_ascii=False, indent=2, default=str))
    write_hashes()
    create_zip()
    print(json.dumps({
        "package": str(ZIP_PATH),
        "package_sha256": sha256(ZIP_PATH),
        "package_bytes": ZIP_PATH.stat().st_size,
        "raw_run_count": len(runs),
        "raw_row_count": sum(len(run["rows"]) for run in runs.values()),
        "graph_count": len(list((OUT / "04_그래프").glob("*.png"))) + len(list((OUT / "05_원자료그래프").glob("*.png"))) + len(list((OUT / "07_도식").glob("*.png"))) + len(list((OUT / "03_유량보정").glob("*.png"))),
        "photo_count": len(list((OUT / "06_사진원본").rglob("*.png"))) + len(list((OUT / "06_사진원본").rglob("*.jpg"))),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
