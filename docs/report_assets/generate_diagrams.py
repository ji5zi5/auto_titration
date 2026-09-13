"""Generate evidence-grounded diagrams for the national science-fair report.

The diagrams contain only values and logic already present in the repository's
experiment records, analysis artifacts, and auto-stop implementation.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


OUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = OUT_DIR.parents[1]
FONT_DIR = Path.home() / ".local/share/fonts/Pretendard"
REGULAR = font_manager.FontProperties(fname=FONT_DIR / "Pretendard-Regular.ttf")
BOLD = font_manager.FontProperties(fname=FONT_DIR / "Pretendard-ExtraBold.otf")

NAVY = "#172B4D"
BLUE = "#2F6BFF"
TEAL = "#0E8A83"
ORANGE = "#E56B2F"
RED = "#C73E4D"
INK = "#27364B"
MUTED = "#627187"
LINE = "#C7D2E2"
PALE_BLUE = "#EDF4FF"
PALE_TEAL = "#EAF8F5"
PALE_ORANGE = "#FFF3E8"
PALE_RED = "#FDEDEF"
WHITE = "#FFFFFF"


def _canvas(*, title: str, subtitle: str = "", figsize: tuple[float, float] = (12, 6)):
    fig, ax = plt.subplots(figsize=figsize, dpi=200)
    fig.patch.set_facecolor(WHITE)
    ax.set_facecolor(WHITE)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.04, 0.93, title, fontproperties=BOLD, fontsize=22, color=NAVY, va="top")
    if subtitle:
        ax.text(0.04, 0.865, subtitle, fontproperties=REGULAR, fontsize=10.5, color=MUTED, va="top")
    return fig, ax


def _box(
    ax,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    body: str = "",
    *,
    face: str = PALE_BLUE,
    edge: str = LINE,
    title_color: str = NAVY,
    title_size: float = 12,
    body_size: float = 9.5,
    radius: float = 0.018,
):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.012,rounding_size={radius}",
        linewidth=1.4,
        edgecolor=edge,
        facecolor=face,
    )
    ax.add_patch(patch)
    ax.text(
        x + w / 2,
        y + h * 0.67,
        title,
        ha="center",
        va="center",
        fontproperties=BOLD,
        fontsize=title_size,
        color=title_color,
    )
    if body:
        ax.text(
            x + w / 2,
            y + h * 0.31,
            body,
            ha="center",
            va="center",
            fontproperties=REGULAR,
            fontsize=body_size,
            color=INK,
            linespacing=1.4,
        )
    return patch


def _arrow(ax, start: tuple[float, float], end: tuple[float, float], *, color: str = BLUE, width: float = 1.6):
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=13,
            linewidth=width,
            color=color,
            connectionstyle="arc3,rad=0",
        )
    )


def _save(fig, name: str):
    fig.savefig(OUT_DIR / name, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)


def research_flow():
    fig, ax = _canvas(
        title="전체 탐구 흐름",
        subtitle="실제 습식 실험과 실험 종료 후 추가한 소프트웨어 검증을 구분하였다.",
        figsize=(13, 6.6),
    )
    stages = [
        ("문제 발견", "사람의 정지 판단과\n과정 기록의 한계", PALE_ORANGE, ORANGE),
        ("판정 기준 설정", "당량점·종말점·\n모델값 구분", PALE_BLUE, BLUE),
        ("장치 제작", "시린지 펌프+\n일반·열화상 카메라", PALE_TEAL, TEAL),
        ("습식 실험", "4종×3농도\n총 12 run", PALE_ORANGE, ORANGE),
        ("자료 감사", "원본 CSV 1,822행\n품질·동기화 확인", PALE_BLUE, BLUE),
        ("재현 모델", "LORO 분석과\n종류별 개발 모델", PALE_TEAL, TEAL),
        ("후속 제어", "기본 OFF 자동정지\n소프트웨어 구현", PALE_RED, RED),
        ("한계·다음 검증", "독립 참값·반복·\nblind wet-run 필요", "#F2F4F7", MUTED),
    ]
    xs = [0.04, 0.275, 0.51, 0.745]
    ys = [0.56, 0.22]
    idx = 0
    centers = []
    for row, y in enumerate(ys):
        order = range(4) if row == 0 else range(3, -1, -1)
        for col in order:
            title, body, face, edge = stages[idx]
            x = xs[col]
            _box(ax, x, y, 0.19, 0.20, title, body, face=face, edge=edge, title_color=edge)
            centers.append((x + 0.095, y + 0.10))
            idx += 1
    for start, end in zip(centers, centers[1:]):
        sx, sy = start
        ex, ey = end
        if abs(sy - ey) < 0.01:
            direction = 1 if ex > sx else -1
            _arrow(ax, (sx + 0.105 * direction, sy), (ex - 0.105 * direction, ey), color=LINE, width=2.0)
        else:
            _arrow(ax, (sx, sy - 0.115), (ex, ey + 0.115), color=LINE, width=2.0)
    ax.text(
        0.5,
        0.08,
        "핵심 원칙  |  측정값·계산값·모델값을 구분하고, 확인한 범위만 결론으로 제시",
        ha="center",
        va="center",
        fontproperties=BOLD,
        fontsize=11,
        color=NAVY,
        bbox=dict(boxstyle="round,pad=0.55", facecolor="#F6F8FB", edgecolor=LINE),
    )
    _save(fig, "research_flow.png")


def system_data_flow():
    fig, ax = _canvas(
        title="자동 적정 보조 시스템의 데이터 흐름",
        subtitle="세 측정 경로를 Windows 대시보드의 공통 시간축에서 결합해 CSV로 저장하였다.",
        figsize=(13, 6.8),
    )
    sources = [
        (0.05, 0.64, "일반 카메라", "용액 ROI\nRGB·HSV·변화량", PALE_BLUE, BLUE),
        (0.05, 0.39, "Mini2 열화상", "ROI 겉보기 표면온도\nraw·변환 출처", PALE_RED, RED),
        (0.05, 0.14, "시린지 펌프", "작동 시간×설정 유량\n0.99 mL/s 계산값", PALE_ORANGE, ORANGE),
    ]
    for x, y, title, body, face, edge in sources:
        _box(ax, x, y, 0.23, 0.16, title, body, face=face, edge=edge, title_color=edge)
        _arrow(ax, (x + 0.24, y + 0.08), (0.39, 0.47), color=edge)
    _box(
        ax,
        0.40,
        0.34,
        0.24,
        0.26,
        "Windows 통합 대시보드",
        "장치 상태·ROI 확인\n공통 시각·동기화 품질\n펌프 명령·CSV 기록",
        face="#EAF0FF",
        edge=BLUE,
        title_color=BLUE,
        title_size=12.5,
    )
    _arrow(ax, (0.65, 0.47), (0.73, 0.47), color=BLUE, width=2.0)
    _box(
        ax,
        0.74,
        0.34,
        0.21,
        0.26,
        "원본 CSV",
        "12 run·1,822행\n색·열·주입량·조건\n추적 가능한 분석 자료",
        face=PALE_TEAL,
        edge=TEAL,
        title_color=TEAL,
        title_size=13,
    )
    ax.text(
        0.5,
        0.075,
        "주의  |  계산 주입량은 실제 토출량 피드백이 아니며, 열화상은 벌크 온도가 아닌 겉보기 표면온도이다.",
        ha="center",
        va="center",
        fontproperties=BOLD,
        fontsize=10.5,
        color=RED,
        bbox=dict(boxstyle="round,pad=0.55", facecolor=PALE_RED, edgecolor="#E9A7AE"),
    )
    _save(fig, "system_data_flow.png")


def experiment_matrix():
    fig, ax = _canvas(
        title="실제 습식 적정 실험 구성",
        subtitle="시료 20.0 mL, 적정액 명목 농도 0.10 M, 각 조건 1회 — 총 12 run",
        figsize=(11.8, 7.0),
    )
    row_labels = ["강산–강염기", "강산–약염기", "약산–강염기", "약산–약염기"]
    col_labels = ["0.10 M", "0.15 M", "0.20 M"]
    row_colors = [BLUE, "#7454D8", ORANGE, TEAL]
    x0, y0, cell_w, cell_h = 0.30, 0.20, 0.20, 0.13
    for j, label in enumerate(col_labels):
        ax.text(
            x0 + j * cell_w + cell_w / 2,
            y0 + 4 * cell_h + 0.065,
            label,
            ha="center",
            va="center",
            fontproperties=BOLD,
            fontsize=12,
            color=NAVY,
        )
    ax.text(0.20, y0 + 4 * cell_h + 0.065, "시료 농도", ha="center", va="center", fontproperties=BOLD, fontsize=11, color=MUTED)
    for i, (label, color) in enumerate(zip(row_labels, row_colors)):
        y = y0 + (3 - i) * cell_h
        ax.text(0.24, y + cell_h / 2, label, ha="right", va="center", fontproperties=BOLD, fontsize=11.2, color=color)
        for j in range(3):
            face = "#F7F9FC" if (i + j) % 2 == 0 else "#EEF3F9"
            rect = FancyBboxPatch(
                (x0 + j * cell_w + 0.01, y + 0.01),
                cell_w - 0.02,
                cell_h - 0.02,
                boxstyle="round,pad=0.006,rounding_size=0.012",
                facecolor=face,
                edgecolor=LINE,
                linewidth=1.1,
            )
            ax.add_patch(rect)
            ax.text(
                x0 + j * cell_w + cell_w / 2,
                y + cell_h / 2,
                "●  1 run",
                ha="center",
                va="center",
                fontproperties=BOLD,
                fontsize=10.5,
                color=color,
            )
    ax.text(
        0.5,
        0.10,
        "조건당 반복 1회이므로 평균·표준편차·일간 재현성은 산출하지 않았다.",
        ha="center",
        va="center",
        fontproperties=BOLD,
        fontsize=11,
        color=RED,
        bbox=dict(boxstyle="round,pad=0.5", facecolor=PALE_RED, edgecolor="#E9A7AE"),
    )
    _save(fig, "experiment_matrix.png")


def ml_pipeline():
    summary_path = REPO_ROOT / "data/ml/type_conditioned_sensor_sequence_search/summary.json"
    with summary_path.open(encoding="utf-8") as handle:
        summary = json.load(handle)
    metrics = summary["per_seed_metrics"][0]
    search_count = summary["configuration_search"]["total_combinations_compared"]

    fig, ax = _canvas(
        title="적정 종류 조건부 센서 시계열 모델의 절차",
        subtitle="색·열 센서 시계열과 사전에 아는 적정 종류만 사용하고, 현재 주입량·시간·진행률·미지 농도·이론 당량점은 입력에서 제외하였다.",
        figsize=(13.2, 6.6),
    )
    stages = [
        ("원본 CSV", "12개 실험\n1,822개 측정점", PALE_BLUE, BLUE),
        ("후보 생성", "색·열 변화의\n여러 시간 폭 후보", PALE_TEAL, TEAL),
        ("외부 LORO", "평가 실험 1개를\n학습·스케일링에서 제외", PALE_ORANGE, ORANGE),
        ("종류별 평가기", "PLS·RBF KRR\nLDA·QDA", "#F1EEFF", "#7454D8"),
        ("후보 점수 집계", "적정 종류별\n정규화·집계", "#F1EEFF", "#7454D8"),
        ("실험별 부피", "선택 프레임의\n기록 부피로 환산", PALE_BLUE, BLUE),
    ]
    x_positions = [0.025, 0.19, 0.355, 0.52, 0.685, 0.85]
    for idx, (x, (title, body, face, edge)) in enumerate(zip(x_positions, stages)):
        _box(ax, x, 0.43, 0.125, 0.22, title, body, face=face, edge=edge, title_color=edge, title_size=10.4, body_size=8.5)
        if idx < len(stages) - 1:
            _arrow(ax, (x + 0.137, 0.54), (x_positions[idx + 1] - 0.012, 0.54), color=LINE, width=2.0)
    ax.text(
        0.5,
        0.27,
        "입력 계약  |  센서 시계열 5개 채널 + 적정 종류 라우팅 / 현재 부피·시간·진행률·미지 농도·이론 당량점 제외",
        ha="center",
        va="center",
        fontproperties=BOLD,
        fontsize=10.3,
        color=NAVY,
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#F6F8FB", edgecolor=LINE),
    )
    ax.text(
        0.5,
        0.115,
        f"사후 개발자료 결과: MAE {metrics['mae_ml']:.3f} mL · RMSE {metrics['rmse_ml']:.3f} mL · "
        f"MAPE {metrics['mape_percent']:.3f}%\n"
        f"총 {search_count:,}개 설정을 같은 12회 자료에서 선택했으므로 독립 일반화 성능이 아니다.",
        ha="center",
        va="center",
        fontproperties=BOLD,
        fontsize=11.5,
        linespacing=1.55,
        color=RED,
        bbox=dict(boxstyle="round,pad=0.65", facecolor=PALE_RED, edgecolor="#E9A7AE"),
    )
    _save(fig, "ml_pipeline.png")


def _development_rows():
    path = REPO_ROOT / "data/ml/report_modality_development_selector/selected_predictions_color_thermal_fusion.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def nominal_vs_development():
    rows = _development_rows()
    actual_values = [float(row["actual_equivalence_volume_ml"]) for row in rows]
    predicted_values = [float(row["predicted_equivalence_volume_ml"]) for row in rows]
    value_range = max(actual_values + predicted_values) - min(actual_values + predicted_values)
    axis_padding = max(1.0, value_range * 0.05)
    axis_min = min(actual_values + predicted_values) - axis_padding
    axis_max = max(actual_values + predicted_values) + axis_padding
    order = [
        "strong_acid_strong_base",
        "strong_acid_weak_base",
        "weak_acid_strong_base",
        "weak_acid_weak_base",
    ]
    labels = {
        "strong_acid_strong_base": "강산–강염기",
        "strong_acid_weak_base": "강산–약염기",
        "weak_acid_strong_base": "약산–강염기",
        "weak_acid_weak_base": "약산–약염기",
    }
    colors = {
        "strong_acid_strong_base": BLUE,
        "strong_acid_weak_base": "#7454D8",
        "weak_acid_strong_base": ORANGE,
        "weak_acid_weak_base": TEAL,
    }
    fig, ax = plt.subplots(figsize=(8.2, 7.2), dpi=200)
    fig.patch.set_facecolor(WHITE)
    ax.set_facecolor(WHITE)
    for key in order:
        selected = [row for row in rows if row["titration_type"] == key]
        x = [float(row["actual_equivalence_volume_ml"]) for row in selected]
        y = [float(row["predicted_equivalence_volume_ml"]) for row in selected]
        ax.scatter(x, y, s=105, label=labels[key], color=colors[key], edgecolor=WHITE, linewidth=1.5, zorder=3)
    ax.plot([axis_min, axis_max], [axis_min, axis_max], color=NAVY, linewidth=2.0, label="완전 일치선", zorder=2)
    ax.set_xlim(axis_min, axis_max)
    ax.set_ylim(axis_min, axis_max)
    ax.set_xlabel("명목 이론부피 (mL)", fontproperties=BOLD, fontsize=12, color=INK)
    ax.set_ylabel("개발자료 재현값 (mL)", fontproperties=BOLD, fontsize=12, color=INK)
    ax.set_title("명목 이론부피와 개발자료 재현값", fontproperties=BOLD, fontsize=21, color=NAVY, pad=18)
    ax.grid(True, color="#DFE5EC", linewidth=0.8)
    ax.tick_params(colors=INK, labelsize=10)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontproperties(REGULAR)
    legend = ax.legend(loc="upper left", prop=REGULAR, fontsize=9.5, frameon=True)
    legend.get_frame().set_edgecolor(LINE)
    legend.get_frame().set_facecolor(WHITE)
    ax.text(
        0.5,
        -0.16,
        "같은 12 run에서 모델을 선택하고 표시한 개발자료 결과이며, 독립 검증값이 아니다.",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontproperties=BOLD,
        fontsize=10.5,
        color=RED,
        bbox=dict(boxstyle="round,pad=0.5", facecolor=PALE_RED, edgecolor="#E9A7AE"),
    )
    fig.tight_layout()
    _save(fig, "nominal_vs_development.png")


def development_relative_deviation():
    rows = _development_rows()
    order = [
        "strong_acid_strong_base",
        "strong_acid_weak_base",
        "weak_acid_strong_base",
        "weak_acid_weak_base",
    ]
    labels = {
        "strong_acid_strong_base": "강산–강염기",
        "strong_acid_weak_base": "강산–약염기",
        "weak_acid_strong_base": "약산–강염기",
        "weak_acid_weak_base": "약산–약염기",
    }
    colors = {
        "strong_acid_strong_base": BLUE,
        "strong_acid_weak_base": "#7454D8",
        "weak_acid_strong_base": ORANGE,
        "weak_acid_weak_base": TEAL,
    }
    sorted_rows = sorted(rows, key=lambda row: (order.index(row["titration_type"]), float(row["concentration_m"])))
    values = [float(row["absolute_percentage_error"]) for row in sorted_rows]
    worst_index = max(range(len(values)), key=values.__getitem__)
    worst_row = sorted_rows[worst_index]
    worst_label = (
        f'{labels[worst_row["titration_type"]]} '
        f'{float(worst_row["concentration_m"]):.2f} M'
    )
    y_max = max(5.0, max(values)) * 1.18
    bar_colors = [colors[row["titration_type"]] for row in sorted_rows]
    tick_labels = [f'{labels[row["titration_type"]]}\n{float(row["concentration_m"]):.2f} M' for row in sorted_rows]
    fig, ax = plt.subplots(figsize=(13.2, 6.8), dpi=200)
    fig.patch.set_facecolor(WHITE)
    ax.set_facecolor(WHITE)
    x = list(range(len(sorted_rows)))
    bars = ax.bar(x, values, color=bar_colors, width=0.66, zorder=3)
    ax.axhline(5.0, color=RED, linewidth=1.8, linestyle="--", zorder=2)
    ax.text(len(x) - 0.15, 5.12, "5%", ha="right", va="bottom", fontproperties=BOLD, fontsize=10.5, color=RED)
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.12,
            f"{value:.2f}%",
            ha="center",
            va="bottom",
            fontproperties=BOLD,
            fontsize=9.2,
            color=NAVY,
        )
    ax.set_title("명목 이론부피 대비 개발자료 상대편차", fontproperties=BOLD, fontsize=21, color=NAVY, pad=18)
    ax.set_ylabel("상대편차 (%)", fontproperties=BOLD, fontsize=12, color=INK)
    ax.set_xticks(x, tick_labels)
    ax.set_ylim(0, y_max)
    ax.grid(axis="y", color="#DFE5EC", linewidth=0.8, zorder=1)
    ax.tick_params(axis="x", colors=INK, labelsize=8.4, rotation=22)
    ax.tick_params(axis="y", colors=INK, labelsize=10)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontproperties(REGULAR)
    ax.text(
        0.5,
        -0.27,
        f"막대 하나는 실제 적정 CSV 한 실험을 뜻한다. {worst_label}의 상대편차가 가장 컸다.",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontproperties=BOLD,
        fontsize=10.5,
        color=MUTED,
    )
    fig.tight_layout()
    _save(fig, "development_relative_deviation.png")


def modality_overall_comparison():
    path = REPO_ROOT / "data/ml/report_modality_sensor_features_only/overall_comparison.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    labels = {
        "color_only": "색상",
        "thermal_only": "열화상",
        "color_thermal_fusion": "색상+열화상",
    }
    colors = {
        "color_only": BLUE,
        "thermal_only": ORANGE,
        "color_thermal_fusion": TEAL,
    }
    order = ["color_only", "thermal_only", "color_thermal_fusion"]
    by_group = {row["group"]: row for row in rows}
    ordered = [by_group[key] for key in order]
    x = list(range(len(order)))

    fig, axes = plt.subplots(1, 2, figsize=(12.8, 5.8), dpi=200)
    fig.patch.set_facecolor(WHITE)
    fig.suptitle("센서 입력군별 당량점 부피 추정 오차", fontproperties=BOLD, fontsize=21, color=NAVY, y=0.98)
    panels = [
        ("mape_percent", "평균 MAPE (%)", 4.2),
        ("mae_ml", "MAE (mL)", 1.08),
    ]
    for ax, (field, ylabel, y_max) in zip(axes, panels):
        values = [float(row[field]) for row in ordered]
        bars = ax.bar(x, values, color=[colors[key] for key in order], width=0.62, zorder=3)
        for bar, value in zip(bars, values):
            suffix = "%" if field == "mape_percent" else " mL"
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + y_max * 0.025,
                f"{value:.2f}{suffix}",
                ha="center",
                va="bottom",
                fontproperties=BOLD,
                fontsize=11,
                color=NAVY,
            )
        ax.set_xticks(x, [labels[key] for key in order])
        ax.set_ylabel(ylabel, fontproperties=BOLD, fontsize=11, color=INK)
        ax.set_ylim(0, y_max)
        ax.grid(axis="y", color="#DFE5EC", linewidth=0.8, zorder=1)
        ax.tick_params(colors=INK, labelsize=10)
        for label in ax.get_xticklabels() + ax.get_yticklabels():
            label.set_fontproperties(REGULAR)
    fig.text(
        0.5,
        0.015,
        "같은 12개 개발자료에서 입력군별 후보를 선택한 결과이며, 독립 검증값은 아니다.",
        ha="center",
        va="bottom",
        fontproperties=BOLD,
        fontsize=10.5,
        color=RED,
        bbox=dict(boxstyle="round,pad=0.45", facecolor=PALE_RED, edgecolor="#E9A7AE"),
    )
    fig.tight_layout(rect=(0, 0.07, 1, 0.93))
    _save(fig, "modality_overall_comparison.png")


def modality_typewise_comparison():
    groups = [
        ("color_only", "색상", BLUE),
        ("thermal_only", "열화상", ORANGE),
        ("color_thermal_fusion", "색상+열화상", TEAL),
    ]
    order = [
        "strong_acid_strong_base",
        "strong_acid_weak_base",
        "weak_acid_strong_base",
        "weak_acid_weak_base",
    ]
    labels = {
        "strong_acid_strong_base": "강산–강염기",
        "strong_acid_weak_base": "강산–약염기",
        "weak_acid_strong_base": "약산–강염기",
        "weak_acid_weak_base": "약산–약염기",
    }
    values_by_group = {}
    for key, _, _ in groups:
        path = REPO_ROOT / f"data/ml/report_modality_sensor_features_only/typewise_selection_{key}.csv"
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        by_type = {row["titration_type"]: float(row["mape_percent_on_available_type_runs"]) for row in rows}
        values_by_group[key] = [by_type[item] for item in order]

    fig, ax = plt.subplots(figsize=(12.8, 6.4), dpi=200)
    fig.patch.set_facecolor(WHITE)
    ax.set_facecolor(WHITE)
    x = list(range(len(order)))
    width = 0.23
    for offset, (key, group_label, color) in zip((-width, 0.0, width), groups):
        values = values_by_group[key]
        bars = ax.bar([i + offset for i in x], values, width=width, label=group_label, color=color, zorder=3)
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + 0.10,
                f"{value:.2f}",
                ha="center",
                va="bottom",
                fontproperties=BOLD,
                fontsize=8.7,
                color=NAVY,
            )
    ax.axhline(5.0, color=RED, linewidth=1.5, linestyle="--", zorder=2)
    ax.text(3.42, 5.10, "5%", ha="right", va="bottom", fontproperties=BOLD, fontsize=10, color=RED)
    ax.set_title("적정 종류별 센서 입력군 MAPE", fontproperties=BOLD, fontsize=21, color=NAVY, pad=18)
    ax.set_ylabel("평균 MAPE (%)", fontproperties=BOLD, fontsize=11, color=INK)
    ax.set_xticks(x, [labels[item] for item in order])
    ax.set_ylim(0, 7.2)
    ax.grid(axis="y", color="#DFE5EC", linewidth=0.8, zorder=1)
    ax.tick_params(colors=INK, labelsize=10)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontproperties(REGULAR)
    legend = ax.legend(prop=REGULAR, fontsize=10, frameon=True, ncol=3, loc="upper left")
    legend.get_frame().set_edgecolor(LINE)
    legend.get_frame().set_facecolor(WHITE)
    ax.text(
        0.5,
        -0.18,
        "열화상 단독 오차는 약산 조건에서 커졌고, 융합의 개선 폭도 적정 종류에 따라 달랐다.",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontproperties=BOLD,
        fontsize=10.5,
        color=MUTED,
    )
    fig.tight_layout()
    _save(fig, "modality_typewise_comparison.png")


def endpoint_method_comparison():
    path = REPO_ROOT / "data/analysis/non_ml_baseline_comparison/overall_comparison.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    labels = {
        "manual_titration_user_provided": "수동 적정\n제공 기록",
        "color_major_slope": "색 기울기",
        "color_thermal_adaptive_threshold": "색·열 임계값",
        "machine_learning_color": "ML\n색상",
        "machine_learning_thermal": "ML\n열화상",
        "machine_learning_fusion": "ML\n색상+열",
        "machine_learning_fusion_with_volume": "ML\n색상+열+주입량",
    }
    colors = {
        "manual_titration_user_provided": "#44546A",
        "color_major_slope": "#7D8AA2",
        "color_thermal_adaptive_threshold": ORANGE,
        "machine_learning_color": BLUE,
        "machine_learning_thermal": "#D59A32",
        "machine_learning_fusion": TEAL,
        "machine_learning_fusion_with_volume": "#7454D8",
    }
    order = [
        "manual_titration_user_provided",
        "color_major_slope",
        "color_thermal_adaptive_threshold",
        "machine_learning_color",
        "machine_learning_thermal",
        "machine_learning_fusion",
        "machine_learning_fusion_with_volume",
    ]
    by_method = {row["method"]: row for row in rows}
    ordered = [by_method[key] for key in order]
    x = list(range(len(order)))

    fig, axes = plt.subplots(1, 2, figsize=(16.0, 6.2), dpi=200)
    fig.patch.set_facecolor(WHITE)
    fig.suptitle("당량점 판정 방식별 오차 비교", fontproperties=BOLD, fontsize=21, color=NAVY, y=0.98)
    panels = [("mape_percent", "평균 MAPE (%)", 7.0), ("mae_ml", "MAE (mL)", 2.6)]
    for ax, (field, ylabel, y_max) in zip(axes, panels):
        values = [float(row[field]) for row in ordered]
        bars = ax.bar(x, values, color=[colors[key] for key in order], width=0.68, zorder=3)
        for bar, value in zip(bars, values):
            suffix = "%" if field == "mape_percent" else " mL"
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + y_max * 0.025,
                f"{value:.2f}{suffix}",
                ha="center",
                va="bottom",
                fontproperties=BOLD,
                fontsize=11,
                color=NAVY,
            )
        if field == "mape_percent":
            ax.axhline(5.0, color=RED, linewidth=1.4, linestyle="--", zorder=2)
            ax.text(
                len(order) - 0.55,
                5.18,
                "5%",
                ha="right",
                va="bottom",
                fontproperties=BOLD,
                fontsize=9.5,
                color=RED,
            )
        ax.set_xticks(x, [labels[key] for key in order])
        ax.set_ylabel(ylabel, fontproperties=BOLD, fontsize=11, color=INK)
        ax.set_ylim(0, y_max)
        ax.grid(axis="y", color="#DFE5EC", linewidth=0.8, zorder=1)
        ax.tick_params(colors=INK, labelsize=9.5)
        for label in ax.get_xticklabels() + ax.get_yticklabels():
            label.set_fontproperties(REGULAR)
    fig.text(
        0.5,
        0.012,
        "수동 적정값은 사용자 제공 기록으로 원자료 대조 전이며, 나머지 여섯 결과는 같은 12개 개발자료 비교값이다.",
        ha="center",
        va="bottom",
        fontproperties=BOLD,
        fontsize=10.3,
        color=RED,
        bbox=dict(boxstyle="round,pad=0.45", facecolor=PALE_RED, edgecolor="#E9A7AE"),
    )
    fig.tight_layout(rect=(0, 0.07, 1, 0.93))
    _save(fig, "endpoint_method_comparison.png")


def repeatability_three_runs():
    values = [0.0823572, 0.08511097, 0.08891732]
    mean = sum(values) / len(values)
    x = [1, 2, 3]
    fig, ax = plt.subplots(figsize=(8.6, 5.8), dpi=200)
    fig.patch.set_facecolor(WHITE)
    ax.set_facecolor(WHITE)
    ax.plot(x, values, color=BLUE, linewidth=2.2, alpha=0.55, zorder=2)
    ax.scatter(x, values, s=125, color=BLUE, edgecolor=WHITE, linewidth=1.5, zorder=3)
    ax.axhline(mean, color=TEAL, linewidth=2.0, linestyle="--", label=f"평균 {mean:.4f} M")
    for xi, value in zip(x, values):
        ax.text(xi, value + 0.00035, f"{value:.4f} M", ha="center", va="bottom", fontproperties=BOLD, fontsize=11, color=NAVY)
    ax.set_title("동일 용액 3회 환산 농도", fontproperties=BOLD, fontsize=21, color=NAVY, pad=18)
    ax.set_xlabel("반복 측정", fontproperties=BOLD, fontsize=11, color=INK)
    ax.set_ylabel("앱의 환산 농도 (M)", fontproperties=BOLD, fontsize=11, color=INK)
    ax.set_xticks(x, ["1회", "2회", "3회"])
    ax.set_ylim(0.080, 0.091)
    ax.grid(axis="y", color="#DFE5EC", linewidth=0.8, zorder=1)
    ax.tick_params(colors=INK, labelsize=10)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontproperties(REGULAR)
    legend = ax.legend(prop=REGULAR, fontsize=10, frameon=True, loc="upper left")
    legend.get_frame().set_edgecolor(LINE)
    legend.get_frame().set_facecolor(WHITE)
    ax.text(
        0.5,
        -0.18,
        "표본 표준편차 0.0033 M · 변동계수 3.85% · 실제 농도 미표정으로 정확도 평가는 아님",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontproperties=BOLD,
        fontsize=10.5,
        color=RED,
    )
    fig.tight_layout()
    _save(fig, "repeatability_three_runs.png")


def auto_stop_state_machine():
    fig, ax = _canvas(
        title="종말점 근처 미세 펄스 주입과 선택형 자동 정지",
        subtitle="이론 당량점 부피를 정지 기준으로 사용하지 않고, 실시간 모델과 지속 색 변화로 제어한다.",
        figsize=(13.2, 7.2),
    )
    _box(ax, 0.035, 0.59, 0.14, 0.16, "사용자 활성화", "기본 OFF\n자동 정지 선택", face="#F2F4F7", edge=MUTED, title_color=MUTED)
    _box(ax, 0.225, 0.59, 0.14, 0.16, "정지 상태 보정", "펌프 정지\nROI 기준색·모델 확인", face=PALE_BLUE, edge=BLUE, title_color=BLUE)
    _box(ax, 0.415, 0.59, 0.18, 0.16, "연속 주입", "b 명령으로 주입\n모델·색 변화 감시", face=PALE_TEAL, edge=TEAL, title_color=TEAL)
    _box(ax, 0.655, 0.59, 0.20, 0.16, "접근 감지", "모델 점수 ≥ 0.20\nc 명령으로 연속 주입 정지", face=PALE_ORANGE, edge=ORANGE, title_color=ORANGE)
    for x1, x2, color in [(0.175, 0.225, LINE), (0.365, 0.415, BLUE), (0.595, 0.655, TEAL)]:
        _arrow(ax, (x1, 0.635), (x2, 0.635), color=color, width=2.0)

    _box(ax, 0.10, 0.29, 0.18, 0.16, "미세 주입", "STEP 5\n수락·완료 응답 확인", face=PALE_BLUE, edge=BLUE, title_color=BLUE)
    _box(ax, 0.365, 0.29, 0.18, 0.16, "혼합 대기", "정지·펄스 뒤 0.50초\n센서값 계속 기록", face=PALE_TEAL, edge=TEAL, title_color=TEAL)
    _box(ax, 0.63, 0.29, 0.20, 0.16, "종말점 재판정", "모델 ≥ 0.30에서 후보 시작\n실제 색 변화 0.4초 지속", face=PALE_ORANGE, edge=ORANGE, title_color=ORANGE)
    _box(ax, 0.855, 0.29, 0.11, 0.16, "최종 정지", "c 명령\nCSV 종료", face=PALE_RED, edge=RED, title_color=RED, title_size=11.5)

    _arrow(ax, (0.755, 0.59), (0.455, 0.47), color=ORANGE, width=2.0)
    _arrow(ax, (0.28, 0.37), (0.365, 0.37), color=BLUE, width=2.0)
    _arrow(ax, (0.545, 0.37), (0.63, 0.37), color=TEAL, width=2.0)
    _arrow(ax, (0.83, 0.37), (0.855, 0.37), color=RED, width=2.0)
    ax.text(0.842, 0.405, "확인", fontproperties=BOLD, fontsize=9.5, color=RED, ha="center")

    _arrow(ax, (0.69, 0.29), (0.23, 0.27), color=ORANGE, width=1.7)
    ax.text(0.47, 0.225, "미확인 → STEP 5와 대기 반복", fontproperties=BOLD, fontsize=9.5, color=ORANGE, ha="center")

    _box(
        ax,
        0.035,
        0.06,
        0.30,
        0.10,
        "안전 제한",
        "회당 기본 15 mL(임시) · 절대 100 mL\n연속 120초 · STEP 1~200",
        face="#F2F4F7",
        edge=MUTED,
        title_color=MUTED,
        title_size=10.8,
        body_size=8.8,
    )
    ax.text(
        0.66,
        0.11,
        "검증 범위  |  소프트웨어·펌웨어 건식 시험 완료\n실제 5스텝 토출량·정지 지연·과주입량은 습식 미검증",
        ha="center",
        va="center",
        fontproperties=BOLD,
        fontsize=10.2,
        color=RED,
        bbox=dict(boxstyle="round,pad=0.55", facecolor=PALE_RED, edgecolor="#E9A7AE"),
    )
    _save(fig, "auto_stop_state_machine.png")


def thermal_sensor_contribution():
    """Visualize paired color-only versus fusion errors without inventing data."""

    source = (
        REPO_ROOT
        / "data/analysis/report_evidence_no_new_wet/color_vs_fusion_paired_errors.csv"
    )
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    labels = [row["run_id"].replace("session-", "S") for row in rows]
    color_errors = [float(row["color_abs_error_ml"]) for row in rows]
    fusion_errors = [float(row["fusion_abs_error_ml"]) for row in rows]
    positions = list(range(len(rows)))
    width = 0.36

    fig, ax = plt.subplots(figsize=(13.2, 7.2), dpi=200)
    fig.patch.set_facecolor(WHITE)
    ax.set_facecolor(WHITE)
    ax.bar(
        [position - width / 2 for position in positions],
        color_errors,
        width,
        color="#5AAFE0",
        label="색상 전용",
    )
    ax.bar(
        [position + width / 2 for position in positions],
        fusion_errors,
        width,
        color="#08A27A",
        label="색상+열화상",
    )
    ax.set_title(
        "실험별 색상 전용과 색상·열화상 융합의 절대오차",
        fontproperties=BOLD,
        fontsize=22,
        color=NAVY,
        loc="left",
        pad=18,
    )
    ax.set_ylabel("절대오차 (mL)", fontproperties=REGULAR, fontsize=13, color=NAVY)
    ax.set_xlabel("기존 12회 실험", fontproperties=REGULAR, fontsize=13, color=NAVY)
    ax.set_xticks(positions, labels, rotation=45, ha="right", fontproperties=REGULAR)
    ax.tick_params(axis="y", labelsize=11, colors=NAVY)
    legend = ax.legend(prop=REGULAR, frameon=False, loc="upper left")
    for text in legend.get_texts():
        text.set_color(NAVY)
    ax.grid(axis="y", alpha=0.25, color=LINE)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color(LINE)
    ax.spines["bottom"].set_color(LINE)
    ax.text(
        0.99,
        0.97,
        "융합 개선 7회 · 악화 5회",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontproperties=BOLD,
        fontsize=11,
        color=ORANGE,
    )
    fig.tight_layout()
    _save(fig, "thermal_sensor_contribution.png")


def main():
    research_flow()
    system_data_flow()
    experiment_matrix()
    ml_pipeline()
    nominal_vs_development()
    development_relative_deviation()
    modality_overall_comparison()
    modality_typewise_comparison()
    endpoint_method_comparison()
    thermal_sensor_contribution()
    auto_stop_state_machine()


if __name__ == "__main__":
    main()
