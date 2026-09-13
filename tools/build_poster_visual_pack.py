#!/usr/bin/env python3
"""Build a print-ready visual asset pack for the national science fair poster."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import textwrap
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

os.environ.setdefault("MPLCONFIGDIR", "/tmp/auto-titration-poster-mpl")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist/poster_visual_pack_2026-08-27"
CHARTS = OUTPUT / "01_핵심그래프"
DIAGRAMS = OUTPUT / "02_구성도와흐름도"
PHOTOS = OUTPUT / "03_실제사진"
SOURCES = OUTPUT / "04_원본수치"
GUIDES = OUTPUT / "05_배치가이드"

FONT_REGULAR = Path("/home/jio/.local/share/fonts/Pretendard/Pretendard-Regular.ttf")
FONT_BOLD = Path("/home/jio/.local/share/fonts/Pretendard/Pretendard-Bold.otf")
FONT_SEMIBOLD = Path("/home/jio/.local/share/fonts/Pretendard/Pretendard-SemiBold.otf")

INK = "#0F172A"
MUTED = "#64748B"
GRID = "#CBD5E1"
PAPER = "#FFFFFF"
SOFT = "#F8FAFC"
BLUE = "#2563EB"
BLUE_LIGHT = "#93C5FD"
ORANGE = "#F59E0B"
ORANGE_LIGHT = "#FCD34D"
GREEN = "#10B981"
GREEN_LIGHT = "#A7F3D0"
RED = "#DC2626"
TYPE_COLORS = {
    "strong_acid_strong_base": "#2563EB",
    "strong_acid_weak_base": "#7C3AED",
    "weak_acid_strong_base": "#0F766E",
    "weak_acid_weak_base": "#64748B",
}
TYPE_KO = {
    "strong_acid_strong_base": "강산-강염기",
    "strong_acid_weak_base": "강산-약염기",
    "weak_acid_strong_base": "약산-강염기",
    "weak_acid_weak_base": "약산-약염기",
}
TYPE_SHORT = {
    "strong_acid_strong_base": "강-강",
    "strong_acid_weak_base": "강-약",
    "weak_acid_strong_base": "약-강",
    "weak_acid_weak_base": "약-약",
}

METHOD_SOURCE = ROOT / "docs/report_revision_figures/source_data/method_comparison.csv"
FUSION_PREDICTIONS = ROOT / "data/ml/report_modality_sensor_features_only/selected_predictions_color_thermal_fusion.csv"
FUSION_TYPEWISE = ROOT / "data/ml/report_modality_sensor_features_only/typewise_selection_color_thermal_fusion.csv"
CURVE_SOURCE = ROOT / "docs/report_evidence_no_new_wet/comparison_visuals/source_data/00_representative_sensor_curves_by_type.csv"
THROUGHPUT_SOURCE = ROOT / "docs/report_revision_figures/source_data/csv_recording_throughput.csv"

PHOTO_SOURCE_ROOT = ROOT / "docs/report_images_organized"
APPARATUS_OVERVIEW = PHOTO_SOURCE_ROOT / "01_system_experiment/01_system_overview_three_views.png"
WET_SETUP = PHOTO_SOURCE_ROOT / "01_system_experiment/12_phenolphthalein_titration_setup.png"
BTB_SETUP = PHOTO_SOURCE_ROOT / "01_system_experiment/13_btb_color_change_setup.png"
REAGENTS = PHOTO_SOURCE_ROOT / "01_system_experiment/11_four_reagent_solutions.png"
PUMP = PHOTO_SOURCE_ROOT / "01_system_experiment/08_completed_syringe_pump.png"
PUMP_PARTS = PHOTO_SOURCE_ROOT / "02_hardware_design/02_syringe_pump_parts_overview.png"
PUMP_3D = PHOTO_SOURCE_ROOT / "02_hardware_design/03_pump_3d_models_overview.png"
CIRCUIT = PHOTO_SOURCE_ROOT / "02_hardware_design/07_arduino_a4988_stepper_circuit.png"
APP_COMPARE = ROOT / "dist/웹GPT_보고서_최종보강자료_2026-08-06/08_보조자료/사진원본/Android앱/Windows_Android_비교화면.png"
WINDOWS_DASHBOARD = ROOT / "dist/웹GPT_보고서_최종보강자료_2026-08-06/08_보조자료/사진원본/Windows앱/Windows_전체대시보드.png"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    columns = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def configure_plot() -> None:
    for path in (FONT_REGULAR, FONT_BOLD, FONT_SEMIBOLD):
        if path.is_file():
            font_manager.fontManager.addfont(path)
    plt.rcParams.update({
        "font.family": "Pretendard",
        "font.size": 12,
        "axes.labelsize": 13,
        "axes.labelcolor": INK,
        "axes.edgecolor": INK,
        "axes.linewidth": 1.0,
        "xtick.color": INK,
        "ytick.color": INK,
        "text.color": INK,
        "figure.facecolor": PAPER,
        "axes.facecolor": PAPER,
        "savefig.facecolor": PAPER,
        "svg.fonttype": "none",
    })


def finish_axis(axis, *, grid_axis: str | None = "y") -> None:
    axis.spines[["top", "right"]].set_visible(False)
    if grid_axis:
        axis.grid(axis=grid_axis, color=GRID, linewidth=0.8, alpha=0.55)
        axis.set_axisbelow(True)
    axis.tick_params(labelsize=11)


def save_figure(fig, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(target, dpi=300, bbox_inches="tight", pad_inches=0.08)
    fig.savefig(target.with_suffix(".svg"), bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)


def method_comparison_chart(rows: Sequence[Mapping[str, str]], target: Path) -> dict[str, Any]:
    logical = [
        "수동 적정", "색 최대 기울기", "색·온도 임계값",
        "ML 색상", "ML 열화상", "ML 색상+열화상",
    ]
    lookup = {row["method"]: row for row in rows}
    selected = [lookup[name] for name in logical]
    values = [float(row["mape_percent"]) for row in selected]
    colors = [MUTED, BLUE_LIGHT, ORANGE_LIGHT, BLUE, ORANGE, GREEN]
    fig, axis = plt.subplots(figsize=(9.2, 5.2), constrained_layout=True)
    y = np.arange(len(selected))
    bars = axis.barh(y, values, color=colors, edgecolor=INK, linewidth=0.7)
    axis.set_yticks(y, [row["method"] for row in selected])
    axis.invert_yaxis()
    axis.set_xlabel("MAPE (%)")
    axis.set_xlim(0, max(values) * 1.24)
    for bar, value in zip(bars, values):
        axis.text(value + 0.10, bar.get_y() + bar.get_height() / 2, f"{value:.2f}%", va="center", fontweight="bold")
    finish_axis(axis, grid_axis="x")
    save_figure(fig, target)
    return {"values": dict(zip(logical, values))}


def modality_chart(rows: Sequence[Mapping[str, str]], target: Path) -> dict[str, Any]:
    lookup = {row["method"]: row for row in rows}
    selected = [lookup["ML 색상"], lookup["ML 열화상"], lookup["ML 색상+열화상"]]
    labels = ["색상", "열화상", "색상+열화상"]
    colors = [BLUE, ORANGE, GREEN]
    mape = [float(row["mape_percent"]) for row in selected]
    mae = [float(row["mae_ml"]) for row in selected]
    rmse = [float(row["rmse_ml"]) for row in selected]
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.8), constrained_layout=True)
    bars = axes[0].bar(labels, mape, color=colors, edgecolor=INK, linewidth=0.7, width=0.65)
    axes[0].set_ylabel("MAPE (%)")
    axes[0].set_ylim(0, max(mape) * 1.32)
    for bar, value in zip(bars, mape):
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + 0.06, f"{value:.2f}%", ha="center", fontweight="bold")
    finish_axis(axes[0])
    x = np.arange(3)
    width = 0.34
    b1 = axes[1].bar(x - width / 2, mae, width, color=colors, edgecolor=INK, linewidth=0.7, label="MAE")
    b2 = axes[1].bar(x + width / 2, rmse, width, color=colors, alpha=0.40, hatch="//", edgecolor=INK, linewidth=0.7, label="RMSE")
    axes[1].set_xticks(x, labels)
    axes[1].set_ylabel("오차 (mL)")
    axes[1].set_ylim(0, max(rmse) * 1.38)
    axes[1].legend(frameon=False, loc="upper left")
    for bars_, values_ in ((b1, mae), (b2, rmse)):
        for bar, value in zip(bars_, values_):
            axes[1].text(bar.get_x() + bar.get_width() / 2, value + 0.025, f"{value:.2f}", ha="center", fontsize=10)
    finish_axis(axes[1])
    save_figure(fig, target)
    return {"mape": dict(zip(labels, mape)), "mae": dict(zip(labels, mae)), "rmse": dict(zip(labels, rmse))}


def typewise_chart(rows: Sequence[Mapping[str, str]], target: Path) -> dict[str, Any]:
    order = ["strong_acid_strong_base", "strong_acid_weak_base", "weak_acid_strong_base", "weak_acid_weak_base"]
    lookup = {row["titration_type"]: row for row in rows}
    values = [float(lookup[key]["mape_percent_on_available_type_runs"]) for key in order]
    fig, axis = plt.subplots(figsize=(8.8, 4.8), constrained_layout=True)
    bars = axis.bar([TYPE_KO[key] for key in order], values, color=GREEN, edgecolor=INK, linewidth=0.7)
    axis.set_ylabel("MAPE (%)")
    axis.set_ylim(0, max(values) * 1.32)
    for bar, value in zip(bars, values):
        axis.text(bar.get_x() + bar.get_width() / 2, value + 0.08, f"{value:.2f}%", ha="center", fontweight="bold")
    finish_axis(axis)
    save_figure(fig, target)
    return {TYPE_KO[key]: value for key, value in zip(order, values)}


def predictions_charts(rows: Sequence[Mapping[str, str]], scatter_target: Path, ape_target: Path) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row["titration_type"], float(row["actual_equivalence_volume_ml"])))
    actual = np.asarray([float(row["actual_equivalence_volume_ml"]) for row in ordered])
    predicted = np.asarray([float(row["predicted_equivalence_volume_ml"]) for row in ordered])
    ape = np.asarray([float(row["absolute_percentage_error"]) for row in ordered])
    fig, axes = plt.subplots(2, 2, figsize=(8.6, 7.2), constrained_layout=True, sharex=True, sharey=True)
    type_order = ["strong_acid_strong_base", "strong_acid_weak_base", "weak_acid_strong_base", "weak_acid_weak_base"]
    limit = (18, 42)
    for axis, key in zip(axes.ravel(), type_order):
        indices = [i for i, row in enumerate(ordered) if row["titration_type"] == key]
        axis.scatter(actual[indices], predicted[indices], s=95, color=GREEN, marker="D", edgecolor=INK, linewidth=0.8, zorder=3)
        axis.plot(limit, limit, color=INK, linestyle="--", linewidth=1.3)
        axis.text(0.04, 0.93, TYPE_KO[key], transform=axis.transAxes, va="top", fontweight="bold", fontsize=12)
        axis.set_xlim(limit)
        axis.set_ylim(limit)
        axis.set_aspect("equal", adjustable="box")
        finish_axis(axis, grid_axis="both")
    axes[1, 0].set_xlabel("이론 당량점 (mL)")
    axes[1, 1].set_xlabel("이론 당량점 (mL)")
    axes[0, 0].set_ylabel("모델 추정 당량점 (mL)")
    axes[1, 0].set_ylabel("모델 추정 당량점 (mL)")
    fig.legend(
        handles=[
            Line2D([], [], color=GREEN, marker="D", linestyle="None", markeredgecolor=INK, label="융합 모델"),
            Line2D([], [], color=INK, linestyle="--", label="이론값과 일치"),
        ],
        frameon=False,
        ncol=2,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.02),
    )
    save_figure(fig, scatter_target)
    conditions = [f"{TYPE_SHORT[row['titration_type']]} {float(row['actual_equivalence_volume_ml']):.0f}" for row in ordered]
    colors = [GREEN if value < 2.0 else ORANGE if value < 5.0 else RED for value in ape]
    display_ape = np.minimum(ape, 5.0)
    fig, axis = plt.subplots(figsize=(10.4, 5.4), constrained_layout=True)
    bars = axis.barh(np.arange(len(ordered)), display_ape, color=colors, edgecolor=INK, linewidth=0.5)
    axis.set_yticks(np.arange(len(ordered)), conditions)
    axis.invert_yaxis()
    axis.set_xlabel("절대백분율오차 (%)")
    axis.axvline(1.0, color=INK, linestyle="--", linewidth=1.2)
    axis.text(1.03, -0.65, "1% 기준", fontsize=9, color=INK, va="center")
    axis.set_xlim(0, 5.65)
    for bar, value in zip(bars, ape):
        x_text = min(float(bar.get_width()) + 0.12, 5.10)
        if abs(value - 1.0) < 0.30:
            x_text = min(x_text + 0.20, 5.10)
        label = f"{value:.2f}%" + (" ↗" if value > 5.0 else "")
        axis.text(x_text, bar.get_y() + bar.get_height() / 2, label, va="center", fontsize=9)
    axis.legend(
        handles=[
            Patch(facecolor=GREEN, edgecolor=INK, label="2% 미만"),
            Patch(facecolor=ORANGE, edgecolor=INK, label="2~5%"),
            Patch(facecolor=RED, edgecolor=INK, label="5% 초과"),
        ],
        frameon=False,
        loc="lower right",
        fontsize=9,
    )
    finish_axis(axis, grid_axis="x")
    save_figure(fig, ape_target)
    return {"run_count": len(rows), "max_ape_percent": float(np.max(ape)), "mape_percent": float(np.mean(ape))}


def normalize(values: np.ndarray) -> np.ndarray:
    finite = values[np.isfinite(values)]
    if not len(finite):
        return np.zeros_like(values)
    lo, hi = np.nanpercentile(finite, [2, 98])
    if hi - lo <= 1e-12:
        return np.zeros_like(values)
    return np.clip((values - lo) / (hi - lo), 0, 1)


def sensor_curves_chart(rows: Sequence[Mapping[str, str]], target: Path) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["titration_type"]].append(row)
    order = ["strong_acid_strong_base", "strong_acid_weak_base", "weak_acid_strong_base", "weak_acid_weak_base"]
    fig, axes = plt.subplots(2, 2, figsize=(11.0, 7.4), constrained_layout=True, sharey=True)
    source_files = []
    for axis, key in zip(axes.ravel(), order):
        current = sorted(grouped[key], key=lambda row: float(row["injected_volume_ml"]))
        volume = np.asarray([float(row["injected_volume_ml"]) for row in current])
        hue = normalize(np.asarray([float(row["visible_H_mean"]) for row in current]))
        thermal = normalize(np.asarray([float(row["thermal_signal"]) for row in current]))
        axis.plot(volume, hue, color=BLUE, linewidth=2.1, label="색조 변화")
        axis.plot(volume, thermal, color=ORANGE, linewidth=2.1, linestyle="--", label="열화상 변화")
        axis.axvline(30.0, color=INK, linewidth=1.3, linestyle=":", label="이론 당량점")
        axis.text(0.03, 0.93, TYPE_KO[key], transform=axis.transAxes, va="top", fontweight="bold", fontsize=13)
        axis.set_xlim(max(0, float(np.min(volume))), float(np.max(volume)))
        axis.set_ylim(-0.03, 1.08)
        finish_axis(axis)
        source_files.append(current[0]["source_file"])
    axes[1, 0].set_xlabel("적정액 주입량 (mL)")
    axes[1, 1].set_xlabel("적정액 주입량 (mL)")
    axes[0, 0].set_ylabel("정규화 변화")
    axes[1, 0].set_ylabel("정규화 변화")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.025), fontsize=12)
    save_figure(fig, target)
    return {"source_files": source_files, "theoretical_line_ml": 30.0}


def experiment_matrix_chart(target: Path) -> dict[str, Any]:
    types = ["강산-강염기", "강산-약염기", "약산-강염기", "약산-약염기"]
    concentrations = ["0.10 M", "0.15 M", "0.20 M"]
    fig, axis = plt.subplots(figsize=(8.4, 4.3), constrained_layout=True)
    axis.set_xlim(-0.8, 3.5)
    axis.set_ylim(-0.15, 4.65)
    axis.axis("off")
    for column, concentration in enumerate(concentrations):
        axis.text(column + 0.5, 4.35, concentration, ha="center", va="center", fontweight="bold")
    for row, label in enumerate(types):
        y = 3.55 - row
        axis.text(-0.10, y + 0.35, label, ha="right", va="center", fontweight="bold")
        for column in range(3):
            box = FancyBboxPatch((column, y), 1.0, 0.70, boxstyle="round,pad=0.02,rounding_size=0.05", facecolor=SOFT, edgecolor=GRID, linewidth=1.5)
            axis.add_patch(box)
            axis.text(column + 0.5, y + 0.35, "1회", ha="center", va="center", color=INK)
    axis.text(1.5, 0.05, "총 12회 · 시계열 측정 1,822행", ha="center", va="center", fontsize=17, fontweight="bold", color=INK)
    save_figure(fig, target)
    return {"run_count": 12, "row_count": 1822, "types": types, "concentrations": concentrations}


def performance_chart(rows: Sequence[Mapping[str, str]], target: Path) -> dict[str, Any]:
    representative = [float(row["representative_rows_per_s"]) for row in rows]
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.5), constrained_layout=True)
    bars = axes[0].bar(["기존 습식 CSV", "25 fps 입력 시험"], representative, color=[MUTED, BLUE], edgecolor=INK, linewidth=0.7)
    axes[0].set_ylabel("CSV 저장 속도 (행/s)")
    axes[0].set_ylim(0, 29)
    for bar, value in zip(bars, representative):
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + 0.7, f"{value:.2f}", ha="center", fontweight="bold")
    finish_axis(axes[0])
    axes[1].axis("off")
    metrics = [
        ("24.93", "행/s", "CSV 지속 저장 · MTlib 변환 포함"),
        ("8.91", "ms", "처리 지연 p95"),
        ("0", "행", "250프레임 누락"),
        ("3.66", "ms", "두 카메라 평균 시각차"),
    ]
    positions = [(0.02, 0.55), (0.52, 0.55), (0.02, 0.05), (0.52, 0.05)]
    for (value, unit, label), (x, y) in zip(metrics, positions):
        box = FancyBboxPatch((x, y), 0.44, 0.38, transform=axes[1].transAxes, boxstyle="round,pad=0.02,rounding_size=0.04", facecolor=SOFT, edgecolor=GRID, linewidth=1.2)
        axes[1].add_patch(box)
        axes[1].text(x + 0.04, y + 0.23, value, transform=axes[1].transAxes, fontsize=23, fontweight="bold", color=BLUE)
        axes[1].text(x + 0.23, y + 0.23, unit, transform=axes[1].transAxes, fontsize=11, color=MUTED)
        axes[1].text(x + 0.04, y + 0.08, label, transform=axes[1].transAxes, fontsize=10.5, color=INK)
    save_figure(fig, target)
    return {"initial_rows_per_s": representative[0], "queue_rows_per_s": representative[1], "official_dll_rows_per_s": 24.93, "p95_ms": 8.91, "dropped": 0, "sync_mean_abs_ms": 3.66}


def diagram_canvas(figsize=(10.8, 4.8)):
    fig, axis = plt.subplots(figsize=figsize, constrained_layout=True)
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")
    return fig, axis


def box(axis, x, y, w, h, text, *, color=BLUE, fill=SOFT, fontsize=12, subtext=None):
    patch = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012,rounding_size=0.025", facecolor=fill, edgecolor=color, linewidth=1.6)
    axis.add_patch(patch)
    axis.text(x + w / 2, y + h * (0.60 if subtext else 0.5), text, ha="center", va="center", fontsize=fontsize, fontweight="bold", color=INK)
    if subtext:
        axis.text(x + w / 2, y + h * 0.28, subtext, ha="center", va="center", fontsize=9.5, color=MUTED)


def arrow(axis, start, end, *, color=MUTED, style="-|>"):
    axis.annotate(
        "",
        xy=end,
        xytext=start,
        arrowprops={
            "arrowstyle": style,
            "mutation_scale": 30,
            "linewidth": 2.2,
            "color": color,
            "shrinkA": 0,
            "shrinkB": 0,
        },
        zorder=10,
    )


def system_diagram(target: Path) -> None:
    fig, axis = diagram_canvas((11.4, 5.0))
    box(axis, 0.03, 0.36, 0.16, 0.25, "시린지 펌프", color=BLUE, subtext="Arduino · A4988")
    box(axis, 0.25, 0.36, 0.16, 0.25, "반응 비커", color=INK, subtext="자석 교반")
    box(axis, 0.47, 0.62, 0.18, 0.22, "일반 카메라", color=BLUE, subtext="RGB · HSV")
    box(axis, 0.47, 0.16, 0.18, 0.22, "열화상 카메라", color=ORANGE, subtext="겉보기 표면온도")
    box(axis, 0.71, 0.36, 0.13, 0.25, "공통 시각", color=MUTED, subtext="CSV 동기화")
    box(axis, 0.88, 0.36, 0.10, 0.25, "당량점", color=GREEN, subtext="농도 계산")
    arrow(axis, (0.19, 0.485), (0.25, 0.485), color=BLUE)
    arrow(axis, (0.41, 0.53), (0.47, 0.70), color=BLUE)
    arrow(axis, (0.41, 0.44), (0.47, 0.27), color=ORANGE)
    arrow(axis, (0.65, 0.72), (0.71, 0.54), color=BLUE)
    arrow(axis, (0.65, 0.27), (0.71, 0.44), color=ORANGE)
    arrow(axis, (0.84, 0.485), (0.88, 0.485), color=GREEN)
    save_figure(fig, target)


def research_flow_diagram(target: Path) -> None:
    fig, axis = diagram_canvas((11.6, 3.05))
    steps = [
        ("문제 인식", "눈 판정 편차"),
        ("장치 제작", "시린지 펌프"),
        ("비접촉 기록", "색상 · 열화상"),
        ("12회 실험", "4종 × 3농도"),
        ("판정 비교", "규칙 · ML"),
        ("농도 계산", "당량점 부피"),
        ("제어 보강", "미세 펄스"),
    ]
    x_positions = np.linspace(0.02, 0.86, len(steps))
    for index, ((label, sub), x) in enumerate(zip(steps, x_positions)):
        color = [MUTED, BLUE, ORANGE, INK, GREEN, BLUE, ORANGE][index]
        box(axis, float(x), 0.26, 0.12, 0.48, label, color=color, subtext=sub, fontsize=11)
        if index < len(steps) - 1:
            arrow(axis, (float(x) + 0.12, 0.50), (float(x_positions[index + 1]), 0.50), color=MUTED)
    save_figure(fig, target)


def jagyeokru_diagram(target: Path) -> None:
    fig, axis = diagram_canvas((11.0, 4.1))
    upper = [("일정한 물 흐름", BLUE), ("누적 물의 양", BLUE), ("경과 시간", BLUE), ("시각 알림", BLUE)]
    lower = [("일정한 모터 구동", GREEN), ("누적 주입량", GREEN), ("센서 변화", ORANGE), ("당량점 표시", GREEN)]
    for row_y, items, prefix in ((0.62, upper, "자격루"), (0.18, lower, "본 장치")):
        axis.text(0.03, row_y + 0.13, prefix, fontsize=14, fontweight="bold", color=INK)
        for index, (label, color) in enumerate(items):
            x = 0.15 + index * 0.215
            box(axis, x, row_y, 0.16, 0.25, label, color=color, fontsize=11)
            if index < 3:
                arrow(axis, (x + 0.16, row_y + 0.125), (x + 0.215, row_y + 0.125), color=MUTED)
    arrow(axis, (0.45, 0.60), (0.45, 0.45), color=MUTED, style="<->")
    axis.text(0.47, 0.525, "시간 ↔ 액체량", va="center", fontsize=11, color=MUTED)
    save_figure(fig, target)


def auto_stop_diagram(target: Path) -> None:
    fig, axis = diagram_canvas((11.7, 3.4))
    steps = [
        ("기준색 확보", BLUE), ("연속 주입", BLUE), ("접근 감지", GREEN),
        ("정지 · 0.50초", ORANGE), ("STEP 5", ORANGE), ("재판정", GREEN), ("종료", INK),
    ]
    x_positions = np.linspace(0.02, 0.87, len(steps))
    for index, ((label, color), x) in enumerate(zip(steps, x_positions)):
        sub = "명목 0.0495 mL" if label == "STEP 5" else None
        box(axis, float(x), 0.50, 0.11, 0.34, label, color=color, subtext=sub, fontsize=10.5)
        if index < len(steps) - 1:
            arrow(axis, (float(x) + 0.11, 0.67), (float(x_positions[index + 1]), 0.67), color=MUTED)
    box(axis, 0.34, 0.08, 0.32, 0.24, "안전 가드", color=RED, fill="#FEF2F2", subtext="시간·누적량·통신 오류 시 즉시 정지")
    arrow(axis, (0.50, 0.32), (0.50, 0.50), color=RED)
    axis.text(0.97, 0.10, "소프트웨어 건식 검증", ha="right", fontsize=10, color=MUTED)
    save_figure(fig, target)


def recording_pipeline_diagram(target: Path) -> None:
    fig, axis = diagram_canvas((11.2, 3.9))
    box(axis, 0.04, 0.37, 0.16, 0.25, "25 fps 입력", color=BLUE, subtext="일반 · 열화상")
    box(axis, 0.28, 0.64, 0.20, 0.22, "미리보기", color=MUTED, subtext="최신 프레임 우선")
    box(axis, 0.28, 0.16, 0.20, 0.22, "기록 대기열", color=BLUE, subtext="FIFO · 누락 방지")
    box(axis, 0.57, 0.16, 0.18, 0.22, "공식 변환기", color=ORANGE, subtext="MTlib DLL")
    box(axis, 0.82, 0.16, 0.14, 0.22, "CSV", color=GREEN, subtext="순서 보존")
    arrow(axis, (0.20, 0.55), (0.28, 0.75), color=MUTED)
    arrow(axis, (0.20, 0.44), (0.28, 0.27), color=BLUE)
    arrow(axis, (0.48, 0.27), (0.57, 0.27), color=ORANGE)
    arrow(axis, (0.75, 0.27), (0.82, 0.27), color=GREEN)
    callout = FancyBboxPatch((0.52, 0.63), 0.44, 0.20, boxstyle="round,pad=0.012,rounding_size=0.025", facecolor=SOFT, edgecolor=GRID, linewidth=1.2)
    axis.add_patch(callout)
    axis.text(0.74, 0.75, "처리 경로 시험", ha="center", fontsize=11, fontweight="bold", color=MUTED)
    axis.text(0.74, 0.68, "CSV 24.93행/s · p95 8.91 ms · 누락 0/250", ha="center", fontsize=12.5, fontweight="bold", color=INK)
    save_figure(fig, target)


def fit_crop(image: Image.Image, width: int, height: int) -> Image.Image:
    return ImageOps.fit(image.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def photo_panel(target: Path, sources: Sequence[Path], *, layout: str = "horizontal", crops: Sequence[tuple[int, int, int, int] | None] | None = None) -> None:
    canvas_width = 2400
    canvas_height = 1450 if layout == "horizontal" else 2100
    canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
    margin = 45
    gap = 35
    images = []
    for index, source in enumerate(sources):
        image = Image.open(source).convert("RGB")
        crop = crops[index] if crops else None
        if crop:
            image = image.crop(crop)
        images.append(image)
    if layout == "horizontal":
        cell_width = (canvas_width - margin * 2 - gap * (len(images) - 1)) // len(images)
        cell_height = canvas_height - margin * 2
        for index, image in enumerate(images):
            fitted = fit_crop(image, cell_width, cell_height)
            x = margin + index * (cell_width + gap)
            canvas.paste(fitted, (x, margin))
    else:
        cell_height = (canvas_height - margin * 2 - gap * (len(images) - 1)) // len(images)
        cell_width = canvas_width - margin * 2
        for index, image in enumerate(images):
            fitted = fit_crop(image, cell_width, cell_height)
            y = margin + index * (cell_height + gap)
            canvas.paste(fitted, (margin, y))
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, dpi=(300, 300), optimize=True)


def labeled_photo_panel(
    target: Path,
    sources: Sequence[Path],
    labels: Sequence[str],
    *,
    crops: Sequence[tuple[int, int, int, int] | None] | None = None,
) -> None:
    canvas_width, canvas_height = 2400, 1450
    margin, gap, label_height = 42, 30, 92
    cell_width = (canvas_width - 2 * margin - gap * (len(sources) - 1)) // len(sources)
    image_height = canvas_height - 2 * margin - label_height
    canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(FONT_SEMIBOLD), 34)
    for index, (source, label) in enumerate(zip(sources, labels)):
        image = Image.open(source).convert("RGB")
        crop = crops[index] if crops else None
        if crop:
            image = image.crop(crop)
        contained = ImageOps.contain(image, (cell_width, image_height), method=Image.Resampling.LANCZOS)
        x = margin + index * (cell_width + gap)
        y = margin + (image_height - contained.height) // 2
        canvas.paste(contained, (x + (cell_width - contained.width) // 2, y))
        draw.rectangle((x, margin, x + cell_width, margin + image_height), outline="#CBD5E1", width=3)
        bbox = draw.textbbox((0, 0), label, font=font)
        draw.text((x + (cell_width - (bbox[2] - bbox[0])) / 2, margin + image_height + 25), label, fill=INK, font=font)
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, dpi=(300, 300), optimize=True)


def panel_font(size: int = 34):
    return ImageFont.truetype(str(FONT_SEMIBOLD), size)


def paste_fitted(canvas: Image.Image, image: Image.Image, box_: tuple[int, int, int, int], *, contain: bool = False) -> None:
    x0, y0, x1, y1 = box_
    target_size = (x1 - x0, y1 - y0)
    prepared = (
        ImageOps.contain(image.convert("RGB"), target_size, method=Image.Resampling.LANCZOS)
        if contain
        else ImageOps.fit(image.convert("RGB"), target_size, method=Image.Resampling.LANCZOS)
    )
    canvas.paste(prepared, (x0 + (target_size[0] - prepared.width) // 2, y0 + (target_size[1] - prepared.height) // 2))
    ImageDraw.Draw(canvas).rectangle(box_, outline="#CBD5E1", width=3)


def draw_panel_label(canvas: Image.Image, box_: tuple[int, int, int, int], text: str, *, size: int = 32) -> None:
    draw = ImageDraw.Draw(canvas)
    font = panel_font(size)
    x0, y0, x1, y1 = box_
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=14, fill="white", outline="#CBD5E1", width=2)
    draw.text((x0 + (x1 - x0 - (bbox[2] - bbox[0])) / 2, y0 + (y1 - y0 - (bbox[3] - bbox[1])) / 2 - bbox[1]), text, fill=INK, font=font)


def apparatus_panel(target: Path) -> None:
    canvas = Image.new("RGB", (2400, 1450), "white")
    wet = Image.open(WET_SETUP).convert("RGB").crop((0, 0, 850, 1301))
    pump = Image.open(PUMP).convert("RGB")
    paste_fitted(canvas, wet, (40, 40, 920, 1320), contain=False)
    paste_fitted(canvas, pump, (960, 40, 2360, 1320), contain=False)
    draw_panel_label(canvas, (40, 1330, 920, 1420), "습식 적정 장치")
    draw_panel_label(canvas, (960, 1330, 2360, 1420), "완성 시린지 펌프")
    canvas.save(target, dpi=(300, 300), optimize=True)


def hardware_panel(target: Path) -> None:
    canvas = Image.new("RGB", (2400, 1450), "white")
    pump = Image.open(PUMP).convert("RGB")
    cad = Image.open(PUMP_3D).convert("RGB")
    circuit = Image.open(CIRCUIT).convert("RGB")
    paste_fitted(canvas, pump, (40, 40, 2360, 650), contain=False)
    paste_fitted(canvas, cad, (40, 760, 1180, 1320), contain=True)
    paste_fitted(canvas, circuit, (1220, 760, 2360, 1320), contain=True)
    draw_panel_label(canvas, (40, 660, 2360, 745), "완성 시린지 펌프")
    draw_panel_label(canvas, (40, 1330, 1180, 1420), "자체 제작 CAD")
    draw_panel_label(canvas, (1220, 1330, 2360, 1420), "Arduino·A4988 회로")
    canvas.save(target, dpi=(300, 300), optimize=True)


def experiment_panel(target: Path) -> None:
    canvas = Image.new("RGB", (2400, 1450), "white")
    phenol = Image.open(WET_SETUP).convert("RGB").crop((180, 180, 900, 1260))
    btb = Image.open(BTB_SETUP).convert("RGB").crop((180, 180, 900, 1270))
    paste_fitted(canvas, phenol, (40, 40, 1180, 1320), contain=False)
    paste_fitted(canvas, btb, (1220, 40, 2360, 1320), contain=False)
    draw_panel_label(canvas, (40, 1330, 1180, 1420), "페놀프탈레인 적정")
    draw_panel_label(canvas, (1220, 1330, 2360, 1420), "BTB 적정")
    canvas.save(target, dpi=(300, 300), optimize=True)


def software_panel(target: Path) -> None:
    dashboard = Image.open(WINDOWS_DASHBOARD).convert("RGB")
    controls = dashboard.crop((90, 0, 1600, 420))
    windows_thermal = dashboard.crop((960, 470, 1600, 930))
    image = Image.open(APP_COMPARE).convert("RGB")
    width, height = image.size
    thermal_raw = image.crop((int(width * 0.75), int(height * 0.05), width, int(height * 0.64)))
    canvas = Image.new("RGB", (2400, 1450), "white")
    draw = ImageDraw.Draw(canvas)
    label_font = ImageFont.truetype(str(FONT_SEMIBOLD), 32)
    warning_font = ImageFont.truetype(str(FONT_BOLD), 34)
    controls_fit = ImageOps.contain(controls, (2300, 570), method=Image.Resampling.LANCZOS)
    windows_fit = ImageOps.fit(windows_thermal, (1060, 600), method=Image.Resampling.LANCZOS)
    thermal_fit = ImageOps.fit(thermal_raw, (1060, 600), method=Image.Resampling.LANCZOS)
    canvas.paste(controls_fit, (50 + (2300 - controls_fit.width) // 2, 30))
    canvas.paste(windows_fit, (50, 660))
    canvas.paste(thermal_fit, (1290, 660))
    draw.rectangle((50, 660, 1110, 1260), outline="#CBD5E1", width=3)
    draw.rectangle((1290, 660, 2350, 1260), outline="#CBD5E1", width=3)
    draw.text((360, 1270), "Windows Mini2 ROI", fill=INK, font=label_font)
    draw.text((1550, 1270), "Android Mini2 raw ROI", fill=INK, font=label_font)
    draw.rounded_rectangle((180, 1340, 2220, 1425), radius=18, fill="#FEF2F2", outline="#DC2626", width=3)
    draw.text((300, 1362), "Android raw 센서값은 ℃가 아니며 섭씨 변환은 미검증", fill=RED, font=warning_font)
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, dpi=(300, 300), optimize=True)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_uri(source: str | Path) -> str:
    path = Path(source)
    if path.is_absolute():
        try:
            return f"pack://{path.relative_to(OUTPUT).as_posix()}"
        except ValueError:
            try:
                return f"repo://{path.relative_to(ROOT).as_posix()}"
            except ValueError:
                return f"file://{path.as_posix()}"
    if str(path).startswith("04_원본수치/"):
        return f"pack://{path.as_posix()}"
    return f"repo://{path.as_posix()}"


def copy_source(path: Path, name: str) -> Path:
    target = SOURCES / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return target


def build() -> dict[str, Any]:
    configure_plot()
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    for directory in (OUTPUT, CHARTS, DIAGRAMS, PHOTOS, SOURCES, GUIDES):
        directory.mkdir(parents=True, exist_ok=True)

    method_rows = read_csv(METHOD_SOURCE)
    prediction_rows = read_csv(FUSION_PREDICTIONS)
    typewise_rows = read_csv(FUSION_TYPEWISE)
    curve_rows = read_csv(CURVE_SOURCE)
    throughput_rows = read_csv(THROUGHPUT_SOURCE)

    source_copies = {
        "method_comparison": copy_source(METHOD_SOURCE, "method_comparison.csv"),
        "fusion_predictions": copy_source(FUSION_PREDICTIONS, "fusion_predictions.csv"),
        "fusion_typewise": copy_source(FUSION_TYPEWISE, "fusion_typewise.csv"),
        "representative_curves": copy_source(CURVE_SOURCE, "representative_sensor_curves.csv"),
        "throughput": copy_source(THROUGHPUT_SOURCE, "csv_recording_throughput.csv"),
    }
    source_originals = {
        "method_comparison": METHOD_SOURCE,
        "fusion_predictions": FUSION_PREDICTIONS,
        "fusion_typewise": FUSION_TYPEWISE,
        "representative_curves": CURVE_SOURCE,
        "throughput": THROUGHPUT_SOURCE,
    }
    source_manifest_rows = [
        {
            "source_id": key,
            "original_source": source_uri(source_originals[key]),
            "pack_copy": source_uri(path),
            "sha256": sha256(source_originals[key]),
        }
        for key, path in source_copies.items()
    ]
    write_csv(SOURCES / "source_manifest.csv", source_manifest_rows)
    system_metrics = [{
        "metric": "camera_sync_mean_absolute_ms", "value": 3.66, "unit": "ms",
        "scope": "12 wet runs, 1822 rows", "source": "docs/science_fair_report_national_formatted.md:283",
    }, {
        "metric": "official_dll_rows_per_s", "value": 24.93, "unit": "rows/s",
        "scope": "250 saved raw frames", "source": "docs/LIVE_PERFORMANCE_VALIDATION.md:35",
    }, {
        "metric": "official_dll_p95_ms", "value": 8.91, "unit": "ms",
        "scope": "250 saved raw frames", "source": "docs/LIVE_PERFORMANCE_VALIDATION.md:35",
    }, {
        "metric": "recording_dropped_rows", "value": 0, "unit": "rows",
        "scope": "250 saved raw frames", "source": "docs/LIVE_PERFORMANCE_VALIDATION.md:35",
    }, {
        "metric": "step5_nominal_ml", "value": 0.0495, "unit": "mL",
        "scope": "nominal software calculation only", "source": "docs/AUTO_STOP_VALIDATION.md:38",
    }]
    write_csv(SOURCES / "system_validation_metrics.csv", system_metrics)
    write_csv(SOURCES / "experiment_summary.csv", [{
        "titration_type_count": 4,
        "concentration_count": 3,
        "run_count": 12,
        "recorded_timeseries_row_count": 1822,
        "theoretical_equivalence_volumes_ml": "20;30;40",
        "source": "repo://docs/science_fair_report_national_formatted.md:283;347",
    }])
    write_csv(SOURCES / "curve_reference.csv", [{
        "sample_concentration_M": 0.15,
        "sample_volume_ml": 20.0,
        "titrant_concentration_M": 0.10,
        "stoichiometric_ratio": 1.0,
        "theoretical_equivalence_volume_ml": 30.0,
        "source": "repo://머신러닝용 파일모음 CSV metadata and 1:1 equivalence calculation",
    }])

    entries: list[dict[str, Any]] = []

    def add(identifier, kind, relative_path, sources, caption, section, width_cm, data=None, note=None):
        path = OUTPUT / relative_path
        entries.append({
            "id": identifier,
            "kind": kind,
            "file": relative_path,
            "svg": str(Path(relative_path).with_suffix(".svg")) if kind in {"chart", "diagram"} else None,
            "source_paths": [source_uri(source) for source in sources],
            "caption": caption,
            "recommended_section": section,
            "recommended_width_cm": width_cm,
            "embedded_title": False,
            "poster_eligible": True,
            "data_summary": data or {},
            "note": note,
        })

    data = method_comparison_chart(method_rows, CHARTS / "01_판정방식_MAPE.png")
    add("chart_method_mape", "chart", "01_핵심그래프/01_판정방식_MAPE.png", [source_copies["method_comparison"]], "수동 적정 기록, 비머신러닝 기준선과 센서 입력군별 머신러닝의 개발자료 MAPE 비교.", "결과", 23.5, data, "모든 수치는 동일 12회 개발자료 비교이며 독립 검증값이 아니다.")
    data = modality_chart(method_rows, CHARTS / "02_센서입력군_비교.png")
    add("chart_modality", "chart", "01_핵심그래프/02_센서입력군_비교.png", [source_copies["method_comparison"]], "색상, 열화상, 색상·열화상 입력군의 MAE·RMSE·MAPE 비교.", "결과", 24.0, data, "12회 개발자료 내부 비교이며 독립 검증값이 아니다. 융합과 색상 전용의 MAPE 차이는 0.03%p이다.")
    data = typewise_chart(typewise_rows, CHARTS / "03_적정종류별_융합MAPE.png")
    add("chart_typewise", "chart", "01_핵심그래프/03_적정종류별_융합MAPE.png", [source_copies["fusion_typewise"]], "색상·열화상 융합 모델의 적정 종류별 개발자료 MAPE.", "결과", 20.0, data, "12회 개발자료 내부 비교이며 독립 검증값이 아니다.")
    data = predictions_charts(prediction_rows, CHARTS / "04_이론값_추정값.png", CHARTS / "05_조건별_오차율.png")
    add("chart_actual_predicted", "chart", "01_핵심그래프/04_이론값_추정값.png", [source_copies["fusion_predictions"]], "12개 조건의 이론 당량점과 색상·열화상 융합 모델 추정값.", "결과", 17.0, data, "12회 개발자료 결과이며 독립 검증 정확도가 아니다.")
    add("chart_condition_ape", "chart", "01_핵심그래프/05_조건별_오차율.png", [source_copies["fusion_predictions"]], "네 적정 종류와 세 농도 조건별 절대백분율오차.", "결과", 22.0, data, "12회 개발자료 결과이며 독립 검증 정확도가 아니다.")
    data = sensor_curves_chart(curve_rows, CHARTS / "06_적정종류별_센서곡선.png")
    add("chart_sensor_curves", "chart", "01_핵심그래프/06_적정종류별_센서곡선.png", [source_copies["representative_curves"], SOURCES / "curve_reference.csv"], "각 적정 종류 0.15 M 대표 실험의 정규화 색조·겉보기 표면온도 변화. 점선은 이론 당량점 30 mL이다.", "원자료", 24.0, data)
    data = experiment_matrix_chart(CHARTS / "07_실험설계_매트릭스.png")
    write_csv(SOURCES / "experiment_design.csv", [
        {"titration_type": key, "titration_type_ko": TYPE_KO[key], "concentration_M": concentration, "run_count": 1}
        for key in TYPE_KO for concentration in (0.10, 0.15, 0.20)
    ])
    add("chart_experiment_matrix", "chart", "01_핵심그래프/07_실험설계_매트릭스.png", [SOURCES / "experiment_design.csv", SOURCES / "experiment_summary.csv"], "네 적정 종류와 세 농도를 조합한 12회 실험 설계와 전체 시계열 측정 1,822행 기록.", "탐구 방법", 19.0, data)
    data = performance_chart(throughput_rows, CHARTS / "08_기록성능_동기화.png")
    add("chart_performance", "chart", "01_핵심그래프/08_기록성능_동기화.png", [source_copies["throughput"], SOURCES / "system_validation_metrics.csv"], "기록 경로 개선 전후 CSV 처리 속도와 MTlib 기반 250프레임 처리·동기화 시험.", "프로그램 개선", 23.0, data, "25 fps 결과는 저장 raw 프레임 처리 경로 시험이며 실제 Mini2 USB 습식 운전 성능이 아니다.")

    system_diagram(DIAGRAMS / "01_전체시스템_구성도.png")
    add("diagram_system", "diagram", "02_구성도와흐름도/01_전체시스템_구성도.png", ["auto_titrator/", "tools/windows_live_collect.py"], "시린지 펌프, 반응 비커, 두 카메라, 공통 시각 기록과 당량점 분석의 연결 구조.", "장치 구성", 23.0)
    research_flow_diagram(DIAGRAMS / "02_연구흐름도.png")
    add("diagram_research_flow", "diagram", "02_구성도와흐름도/02_연구흐름도.png", ["docs/science_fair_report_national_formatted.md"], "문제 인식부터 장치 제작·실험·분석·제어 보강까지의 연구 흐름.", "연구 개요", 24.0)
    jagyeokru_diagram(DIAGRAMS / "03_자격루_원리비교.png")
    add("diagram_jagyeokru", "diagram", "02_구성도와흐름도/03_자격루_원리비교.png", ["docs/science_fair_report_national_formatted.md"], "자격루의 시간-액체량 연결과 본 장치의 시간-주입량-센서 판정 구조 비교.", "연구 동기", 22.0)
    auto_stop_diagram(DIAGRAMS / "04_미세주입_자동정지.png")
    add("diagram_auto_stop", "diagram", "02_구성도와흐름도/04_미세주입_자동정지.png", ["docs/AUTO_STOP_VALIDATION.md", SOURCES / "system_validation_metrics.csv"], "종말점 접근 뒤 연속 주입을 멈추고 STEP 5 펄스와 재판정을 반복하는 건식 검증 상태 흐름.", "프로그램 개선", 24.0, {"step5_nominal_ml": 0.0495}, "0.0495 mL는 실측 방울 부피가 아닌 명목 계산값이다.")
    recording_pipeline_diagram(DIAGRAMS / "05_25fps_기록파이프라인.png")
    add("diagram_recording", "diagram", "02_구성도와흐름도/05_25fps_기록파이프라인.png", ["docs/LIVE_PERFORMANCE_VALIDATION.md", SOURCES / "system_validation_metrics.csv"], "미리보기와 FIFO 기록 경로를 분리한 25 fps 처리 구조.", "프로그램 개선", 22.0, {"rows_per_s": 24.93, "p95_ms": 8.91, "dropped": 0}, "저장 raw 프레임 처리 경로 시험이며 실제 Mini2 USB 습식 캡처 성능이 아니다.")

    apparatus_panel(PHOTOS / "01_장치_실험전경.png")
    add("photo_apparatus", "photo", "03_실제사진/01_장치_실험전경.png", [WET_SETUP, PUMP], "완성한 비접촉 스마트 적정 장치와 시린지 펌프.", "장치 제작", 23.0)
    hardware_panel(PHOTOS / "02_펌프_CAD_회로.png")
    add("photo_hardware", "photo", "03_실제사진/02_펌프_CAD_회로.png", [PUMP, PUMP_3D, CIRCUIT], "완성 시린지 펌프, 자체 제작 CAD와 Arduino-A4988 회로.", "장치 제작", 24.0)
    experiment_panel(PHOTOS / "03_습식실험_시약.png")
    add("photo_experiment", "photo", "03_실제사진/03_습식실험_시약.png", [WET_SETUP, BTB_SETUP], "페놀프탈레인과 BTB를 사용한 실제 적정 장면.", "실험 방법", 24.0)
    software_panel(PHOTOS / "04_Windows_Android_화면.png")
    add("photo_software", "photo", "03_실제사진/04_Windows_Android_화면.png", [WINDOWS_DASHBOARD, APP_COMPARE], "Windows 제어·ROI 화면과 Android Mini2 raw/ROI 확인 화면.", "프로그램", 22.0, note="Android 열화상 값은 raw 상태이며 섭씨로 해석하지 않는다.")

    required = [entry["id"] for entry in entries]
    manifest = {
        "schema_version": "poster_visual_pack_v1",
        "generated_date": "2026-08-27",
        "project_title": "자격루의 원리와 열, 색감지 머신러닝을 융합한 비접촉식 스마트 적정기 개발",
        "output_root": str(OUTPUT.relative_to(ROOT)),
        "source_path_bases": {
            "repo://": str(ROOT),
            "pack://": str(OUTPUT),
        },
        "palette": {"color": BLUE, "thermal": ORANGE, "fusion": GREEN, "ink": INK, "paper": PAPER},
        "style": {"font": "Pretendard", "png_dpi": 300, "minimum_width_px": 1800, "embedded_titles": False},
        "scientific_scope": {
            "poster_performance_values": "1.55% color, 3.66% thermal, 1.52% fusion; same-12-run development comparison",
            "excluded_posthoc_values": [0.295, 0.340],
            "thermal_policy": "Only validated Windows apparent-surface-temperature data may use Celsius; Android Mini2 raw remains raw.",
            "auto_stop_policy": "STEP 5 = nominal 0.0495 mL, dry-tested software only.",
        },
        "required_asset_ids": required,
        "assets": entries,
        "source_files": {
            key: {
                "original": source_uri(source_originals[key]),
                "pack_copy": source_uri(path),
                "sha256": sha256(source_originals[key]),
            }
            for key, path in source_copies.items()
        },
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    guide = [
        "# 전국과학전람회 포스터 시각자료 배치 가이드", "",
        "## 우선 배치 10개", "",
        "1. 실제 장치 전경 — `03_실제사진/01_장치_실험전경.png`",
        "2. 자격루 원리 비교 — `02_구성도와흐름도/03_자격루_원리비교.png`",
        "3. 전체 시스템 구성 — `02_구성도와흐름도/01_전체시스템_구성도.png`",
        "4. 실험 설계 매트릭스 — `01_핵심그래프/07_실험설계_매트릭스.png`",
        "5. 적정 종류별 센서 곡선 — `01_핵심그래프/06_적정종류별_센서곡선.png`",
        "6. 판정 방식 MAPE — `01_핵심그래프/01_판정방식_MAPE.png`",
        "7. 센서 입력군 비교 — `01_핵심그래프/02_센서입력군_비교.png`",
        "8. 이론값-추정값 — `01_핵심그래프/04_이론값_추정값.png`",
        "9. 적정 종류별 융합 MAPE — `01_핵심그래프/03_적정종류별_융합MAPE.png`",
        "10. 기록 성능·동기화 — `01_핵심그래프/08_기록성능_동기화.png`", "",
        "## 사용 규칙", "",
        "- 그림 내부에 별도 제목을 추가하지 않고 포스터 편집기에서 그림 번호와 캡션을 붙인다.",
        "- 색상 신호는 파랑, 열화상은 주황, 융합은 초록으로 유지한다.",
        "- 0.295%·0.340% 사후 설정선택 결과는 포스터 성능값으로 사용하지 않는다.",
        "- 1.55%·3.66%·1.52%는 ‘12회 개발자료 내부 비교’로 표기한다.",
        "- Android Mini2 raw 값에 ℃를 붙이지 않는다.",
        "- STEP 5의 0.0495 mL는 ‘명목 계산값·건식 시험’으로만 표기한다.", "",
        "## 전체 캡션", "",
    ]
    for index, entry in enumerate(entries, 1):
        guide.append(f"- 그림 {index}. {entry['caption']} (`{entry['file']}`)")
    (GUIDES / "포스터_배치가이드.md").write_text("\n".join(guide) + "\n", encoding="utf-8")

    captions = [{"id": entry["id"], "file": entry["file"], "caption": entry["caption"], "section": entry["recommended_section"], "width_cm": entry["recommended_width_cm"], "note": entry["note"] or ""} for entry in entries]
    write_csv(GUIDES / "캡션_목록.csv", captions)

    checksummed = sorted(path for path in OUTPUT.rglob("*") if path.is_file() and path.name not in {"SHA256SUMS.txt"})
    (OUTPUT / "SHA256SUMS.txt").write_text("".join(f"{sha256(path)}  {path.relative_to(OUTPUT)}\n" for path in checksummed), encoding="utf-8")
    zip_path = ROOT / "dist/poster_visual_pack_2026-08-27.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(OUTPUT.rglob("*")):
            if path.is_file():
                archive.write(path, Path(OUTPUT.name) / path.relative_to(OUTPUT))
    return manifest


def main() -> int:
    manifest = build()
    print(json.dumps({"output": str(OUTPUT), "asset_count": len(manifest["assets"]), "zip": str(ROOT / "dist/poster_visual_pack_2026-08-27.zip")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
