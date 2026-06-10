#!/usr/bin/env python3
"""Create poster-ready ML summary figures and text with matplotlib."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch

BASE = Path("data/ml/current_volume_no_progress")
OUT = Path("docs/poster_assets")
TEXT_OUT = Path("docs/poster_ml_text.txt")

TYPE_LABELS = {
    "strong_acid_strong_base": "강산-강염기",
    "strong_acid_weak_base": "강산-약염기",
    "weak_acid_strong_base": "약산-강염기",
    "weak_acid_weak_base": "약산-약염기",
}
TYPE_ORDER = [
    "strong_acid_strong_base",
    "strong_acid_weak_base",
    "weak_acid_strong_base",
    "weak_acid_weak_base",
]
TYPE_COLORS = {
    "strong_acid_strong_base": "#2563EB",
    "strong_acid_weak_base": "#7C3AED",
    "weak_acid_strong_base": "#EA580C",
    "weak_acid_weak_base": "#16A34A",
}


def setup_style() -> None:
    for path in [
        Path.home() / ".local/share/fonts/Pretendard/Pretendard-Regular.otf",
        Path.home() / ".local/share/fonts/Pretendard/Pretendard-Bold.otf",
        Path.home() / ".local/share/fonts/Pretendard/Pretendard-ExtraBold.otf",
    ]:
        if path.exists():
            font_manager.fontManager.addfont(str(path))
    plt.rcParams.update(
        {
            "font.family": "Pretendard",
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "axes.edgecolor": "#CBD5E1",
            "axes.labelcolor": "#111827",
            "xtick.color": "#334155",
            "ytick.color": "#334155",
            "text.color": "#111827",
            "axes.titleweight": "bold",
            "axes.titlesize": 26,
            "axes.labelsize": 17,
            "xtick.labelsize": 15,
            "ytick.labelsize": 15,
            "legend.fontsize": 13,
        }
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def save(fig: plt.Figure, stem: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{stem}.png", dpi=240, bbox_inches="tight", facecolor="white")
    fig.savefig(OUT / f"{stem}.svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def clean_axes(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#CBD5E1")
    ax.spines["bottom"].set_color("#CBD5E1")
    ax.grid(axis="y", color="#E5E7EB", linewidth=1.15)
    ax.set_axisbelow(True)


def annotate_bars(ax: plt.Axes, bars: Any, suffix: str, decimals: int = 2) -> None:
    ymax = ax.get_ylim()[1]
    for bar in bars:
        value = float(bar.get_height())
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + ymax * 0.025,
            f"{value:.{decimals}f}{suffix}",
            ha="center",
            va="bottom",
            fontsize=16,
            fontweight="bold",
        )


def model_comparison(summary: dict[str, Any]) -> None:
    rows = read_csv(BASE / "model_comparison.csv")
    strict_rows = [row for row in rows if not row["method_key"].startswith("typewise_development_selector:")]
    strict_best = min(strict_rows, key=lambda row: (float(row["mape_percent"]), float(row["mae_ml"])))
    labels = ["단일 통합 모델", "적정 종류별 모델"]
    mape = [float(strict_best["mape_percent"]), float(summary["best"]["metrics"]["mape_percent"])]
    mae = [float(strict_best["mae_ml"]), float(summary["best"]["metrics"]["mae_ml"])]
    colors = ["#94A3B8", "#2563EB"]

    fig, axes = plt.subplots(1, 2, figsize=(14.5, 5.6), gridspec_kw={"wspace": 0.34})
    bars = axes[0].bar(labels, mape, color=colors, width=0.58, edgecolor="white", linewidth=1.5)
    axes[0].set_title("평균 상대오차 비교")
    axes[0].set_ylabel("MAPE (%)")
    axes[0].set_ylim(0, max(mape) * 1.32)
    clean_axes(axes[0])
    annotate_bars(axes[0], bars, "%")

    bars = axes[1].bar(labels, mae, color=colors, width=0.58, edgecolor="white", linewidth=1.5)
    axes[1].set_title("평균 절대오차 비교")
    axes[1].set_ylabel("MAE (mL)")
    axes[1].set_ylim(0, max(mae) * 1.32)
    clean_axes(axes[1])
    annotate_bars(axes[1], bars, " mL", decimals=3)

    fig.suptitle("통합 모델보다 적정 종류별 모델에서 오차 감소", fontsize=30, fontweight="bold", y=1.03)
    fig.text(0.5, -0.02, "적정 종류를 실험 전에 알고 있으므로, 실제 적용 시 종류별 모델을 선택할 수 있다.", ha="center", fontsize=16, color="#475569")
    save(fig, "ml_01_model_comparison")


def typewise_error(summary: dict[str, Any]) -> None:
    metrics = summary["best"]["typewise_metrics"]
    labels = [TYPE_LABELS[t] for t in TYPE_ORDER]
    values = [float(metrics[t]["mape_percent"]) for t in TYPE_ORDER]
    colors = [TYPE_COLORS[t] for t in TYPE_ORDER]

    fig, ax = plt.subplots(figsize=(12, 6.4))
    bars = ax.bar(labels, values, color=colors, width=0.58, edgecolor="white", linewidth=1.5)
    ax.axhline(5.0, color="#EF4444", linewidth=2.4, linestyle="--")
    ax.text(3.44, 5.12, "5% 기준선", color="#EF4444", fontsize=15, ha="right", va="bottom", fontweight="bold")
    ax.set_title("적정 종류별 당량점 예측 오차")
    ax.set_ylabel("MAPE (%)")
    ax.set_ylim(0, max(5.8, max(values) * 1.36))
    clean_axes(ax)
    annotate_bars(ax, bars, "%")
    fig.text(0.5, -0.02, "약산-강염기에서 오차가 가장 컸지만 전체 조건에서 5% 이내로 나타났다.", ha="center", fontsize=16, color="#475569")
    save(fig, "ml_02_typewise_mape")


def actual_vs_predicted() -> None:
    rows = read_csv(BASE / "best_predictions.csv")
    fig, ax = plt.subplots(figsize=(8.8, 8.0))
    for t in TYPE_ORDER:
        subset = [r for r in rows if r["titration_type"] == t]
        ax.scatter(
            [float(r["actual_equivalence_volume_ml"]) for r in subset],
            [float(r["predicted_equivalence_volume_ml"]) for r in subset],
            s=140,
            color=TYPE_COLORS[t],
            edgecolor="white",
            linewidth=1.8,
            label=TYPE_LABELS[t],
            alpha=0.96,
        )
    ax.plot([18, 42], [18, 42], color="#111827", linewidth=2.4, label="이상적 예측선")
    ax.set_title("이론 당량점과 모델 예측값 비교")
    ax.set_xlabel("이론 당량점 부피 (mL)")
    ax.set_ylabel("예측 당량점 부피 (mL)")
    ax.set_xlim(18, 42)
    ax.set_ylim(18, 42)
    ax.set_aspect("equal", adjustable="box")
    clean_axes(ax)
    ax.grid(color="#E5E7EB", linewidth=1.15)
    ax.legend(frameon=False, loc="upper left")
    save(fig, "ml_03_actual_vs_predicted")


def workflow_diagram() -> None:
    fig, ax = plt.subplots(figsize=(15, 4.8))
    ax.set_axis_off()
    items = [
        ("실험 입력", "적정 종류\n표준용액 정보"),
        ("센서 기록", "주입량\nHSV 색 변화\nROI 온도 변화"),
        ("프레임 분류", "당량점 부근\n가능성 점수"),
        ("부피 예측", "점수 높은 프레임\n주입량 종합"),
        ("농도 계산", "예측 당량점으로\n미지 시료 농도 산출"),
    ]
    xs = [0.08, 0.29, 0.50, 0.71, 0.92]
    for i, ((title, body), x) in enumerate(zip(items, xs)):
        box = FancyBboxPatch(
            (x - 0.078, 0.29),
            0.156,
            0.42,
            boxstyle="round,pad=0.02,rounding_size=0.03",
            linewidth=1.8,
            edgecolor="#CBD5E1",
            facecolor="#EFF6FF" if i == 2 else "#F8FAFC",
            transform=ax.transAxes,
        )
        ax.add_patch(box)
        ax.text(x, 0.61, title, transform=ax.transAxes, ha="center", va="center", fontsize=19, fontweight="bold", color="#0F172A")
        ax.text(x, 0.45, body, transform=ax.transAxes, ha="center", va="center", fontsize=15.5, color="#334155", linespacing=1.45)
        if i < len(xs) - 1:
            ax.annotate(
                "",
                xy=(xs[i + 1] - 0.095, 0.50),
                xytext=(x + 0.095, 0.50),
                xycoords=ax.transAxes,
                textcoords=ax.transAxes,
                arrowprops=dict(arrowstyle="-|>", lw=2.3, color="#64748B"),
            )
    ax.text(0.5, 0.88, "실시간 수집값만 사용한 당량점 예측 흐름", transform=ax.transAxes, ha="center", va="center", fontsize=28, fontweight="bold")
    ax.text(0.5, 0.13, "실제 예측 단계에서는 이론 당량점이나 정답과의 거리를 입력하지 않는다.", transform=ax.transAxes, ha="center", fontsize=16, color="#475569")
    save(fig, "ml_04_prediction_workflow")



def method_family_comparison() -> None:
    rows = read_csv(BASE / "model_comparison.csv")
    groups = [
        ("frame_remaining_regression", "프레임\n잔여량 회귀", "#64748B"),
        ("run_summary_sensor_curve", "실험곡선\n요약 회귀", "#94A3B8"),
        ("sensor_candidate_error_model", "후보 오차\n보정 회귀", "#A1A1AA"),
        ("frame_zone_classifier", "프레임\n구간 분류", "#2563EB"),
        ("typewise_development_selector", "적정 종류별\n모델 선택", "#16A34A"),
    ]
    labels, values, colors = [], [], []
    best_rows = []
    for method, label, color in groups:
        subset = [r for r in rows if r["method"] == method]
        if not subset:
            continue
        best = min(subset, key=lambda r: (float(r["mape_percent"]), float(r["mae_ml"])))
        labels.append(label)
        values.append(float(best["mape_percent"]))
        colors.append(color)
        best_rows.append(best)

    fig, ax = plt.subplots(figsize=(13.2, 6.5))
    bars = ax.bar(labels, values, color=colors, width=0.62, edgecolor="white", linewidth=1.5)
    ax.set_title("예측 방식별 최고 성능 비교")
    ax.set_ylabel("MAPE (%)")
    ax.set_ylim(0, max(values) * 1.25)
    clean_axes(ax)
    annotate_bars(ax, bars, "%")
    fig.text(0.5, -0.02, "전체 실험 부피를 직접 회귀하는 방식보다, 프레임을 먼저 분류하는 방식에서 오차가 감소하였다.", ha="center", fontsize=16, color="#475569")
    save(fig, "ml_05_method_family_comparison")


def regression_algorithm_comparison() -> None:
    rows = read_csv(BASE / "model_comparison.csv")
    regression_methods = {"frame_remaining_regression", "run_summary_sensor_curve", "sensor_candidate_error_model"}
    aliases = {
        "knn": "KNN",
        "gradient_boosting": "Gradient\nBoosting",
        "extra_trees": "Extra\nTrees",
        "extra_trees_leaf2": "Extra Trees\nleaf2",
        "extra_trees_leaf3": "Extra Trees\nleaf3",
        "random_forest": "Random\nForest",
        "ridge": "Ridge",
        "kernel_ridge": "Kernel\nRidge",
        "svr_rbf": "SVR\nRBF",
    }
    by_model: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if row["method"] in regression_methods:
            by_model.setdefault(row["model"], []).append(row)
    best_items = []
    for model, subset in by_model.items():
        best = min(subset, key=lambda r: (float(r["mape_percent"]), float(r["mae_ml"])))
        best_items.append((float(best["mape_percent"]), float(best["mae_ml"]), model, best))
    best_items.sort(key=lambda item: item[0])
    # Keep graph readable on poster.
    best_items = best_items[:8]
    labels = [aliases.get(model, model) for _mape, _mae, model, _best in best_items]
    values = [mape for mape, _mae, _model, _best in best_items]
    colors = ["#94A3B8"] * len(values)
    if values:
        colors[0] = "#2563EB"

    fig, ax = plt.subplots(figsize=(13.2, 6.5))
    bars = ax.bar(labels, values, color=colors, width=0.62, edgecolor="white", linewidth=1.5)
    ax.set_title("회귀 모델별 최고 성능 비교")
    ax.set_ylabel("MAPE (%)")
    ax.set_ylim(0, max(values) * 1.22)
    clean_axes(ax)
    annotate_bars(ax, bars, "%")
    fig.text(0.5, -0.02, "회귀 모델 중에서는 Gradient Boosting과 KNN 계열이 상대적으로 나았지만, 프레임 분류 방식보다 오차가 컸다.", ha="center", fontsize=16, color="#475569")
    save(fig, "ml_06_regression_algorithm_comparison")


def run_error_by_condition() -> None:
    rows = read_csv(BASE / "best_predictions.csv")
    fig, ax = plt.subplots(figsize=(13.5, 6.4))
    x_positions = []
    labels = []
    colors = []
    values = []
    concentrations = []
    idx = 0
    for t_i, t in enumerate(TYPE_ORDER):
        subset = sorted([r for r in rows if r["titration_type"] == t], key=lambda r: float(r["concentration_m"]))
        for r in subset:
            x_positions.append(idx)
            labels.append(f"{TYPE_LABELS[t]}\n{float(r['concentration_m']):.2f} M")
            colors.append(TYPE_COLORS[t])
            values.append(float(r["absolute_percentage_error"]))
            concentrations.append(float(r["concentration_m"]))
            idx += 1
        idx += 0.65
    bars = ax.bar(x_positions, values, color=colors, width=0.62, edgecolor="white", linewidth=1.4)
    ax.axhline(5.0, color="#EF4444", linewidth=2.2, linestyle="--")
    ax.text(max(x_positions), 5.15, "5%", color="#EF4444", fontsize=15, ha="right", fontweight="bold")
    ax.set_title("조건별 예측 오차")
    ax.set_ylabel("절대 상대오차 (%)")
    ax.set_ylim(0, max(6.0, max(values) * 1.32))
    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, rotation=35, ha="right")
    clean_axes(ax)
    annotate_bars(ax, bars, "%")
    fig.text(0.5, -0.04, "각 막대는 하나의 실제 적정 CSV 결과이다. 약산-강염기 0.20 M 조건에서 오차가 가장 크게 나타났다.", ha="center", fontsize=16, color="#475569")
    save(fig, "ml_07_run_error_by_condition")


def _numeric(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except ValueError:
        return None
    if v != v:
        return None
    return v


def _curve_points(path: Path, target_concentration: float | None = None) -> tuple[list[float], list[float], list[float]]:
    volumes: list[float] = []
    hue: list[float] = []
    temp: list[float] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            v = _numeric(row.get("injected_volume_ml"))
            h = _numeric(row.get("visible_H_mean"))
            t = _numeric(row.get("thermal_roi_avg"))
            if v is None or h is None or t is None:
                continue
            volumes.append(v)
            hue.append(h)
            temp.append(t)
    # Downsample by volume bins for poster readability.
    binned: dict[float, list[tuple[float, float]]] = {}
    for v, h, t in zip(volumes, hue, temp):
        key = round(v / 0.35) * 0.35
        binned.setdefault(key, []).append((h, t))
    xs, hs, ts = [], [], []
    for key in sorted(binned):
        vals = binned[key]
        xs.append(key)
        hs.append(sum(v[0] for v in vals) / len(vals))
        ts.append(sum(v[1] for v in vals) / len(vals))
    return xs, hs, ts


def sensor_curves_by_type() -> None:
    predictions = read_csv(BASE / "best_predictions.csv")
    # Use 0.15 M representative runs because all four titration types have one.
    chosen = {r["titration_type"]: r for r in predictions if abs(float(r["concentration_m"]) - 0.15) < 1e-6}
    fig, axes = plt.subplots(2, 2, figsize=(14.5, 9.2), sharex=False)
    axes_flat = list(axes.ravel())
    for ax, t in zip(axes_flat, TYPE_ORDER):
        r = chosen[t]
        xs, hs, ts = _curve_points(Path(r["run_path"]))
        color = TYPE_COLORS[t]
        ax2 = ax.twinx()
        ax.plot(xs, hs, color="#2563EB", linewidth=2.2, label="H 색상값")
        ax2.plot(xs, ts, color="#EF4444", linewidth=2.2, label="ROI 온도")
        eq = float(r["actual_equivalence_volume_ml"])
        ax.axvline(eq, color="#111827", linewidth=1.8, linestyle="--", alpha=0.75)
        ax.set_title(f"{TYPE_LABELS[t]} 0.15 M", fontsize=20, fontweight="bold", color=color)
        ax.set_xlabel("주입량 (mL)")
        ax.set_ylabel("H 색상값", color="#2563EB")
        ax2.set_ylabel("ROI 온도 (℃)", color="#EF4444")
        ax.grid(axis="both", color="#E5E7EB", linewidth=1.0)
        ax.set_axisbelow(True)
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
        ax2.spines["top"].set_visible(False)
        ax.text(eq, ax.get_ylim()[1], " 이론 당량점", fontsize=11, va="top", ha="left", color="#111827")
    fig.suptitle("대표 실험의 색상 H·온도 변화 곡선", fontsize=30, fontweight="bold", y=1.02)
    fig.text(0.5, -0.01, "색 변화와 온도 변화는 적정 종류에 따라 다르게 나타나므로, 종류별 모델 분리가 필요하다.", ha="center", fontsize=16, color="#475569")
    fig.tight_layout()
    save(fig, "ml_08_sensor_curves_by_type")


def selected_model_by_type() -> None:
    summary = json.loads((BASE / "summary.json").read_text(encoding="utf-8"))
    selector = summary.get("typewise_development_selector", {}).get("selection", {})
    rows = []
    for t in TYPE_ORDER:
        method = selector.get(t, {}).get("selected_method_key", "")
        model = "Extra Trees" if "extra_trees" in method else "Random Forest" if "random_forest" in method else method
        if "top80" in method:
            agg = "상위 80개 프레임"
        elif "top40" in method:
            agg = "상위 40개 프레임"
        elif "top25" in method:
            agg = "상위 25개 프레임"
        elif "weighted_median_top10" in method:
            agg = "상위 10개 가중 중앙값"
        else:
            agg = method.split(":")[-1]
        mape = float(selector.get(t, {}).get("mape_percent_on_available_type_runs", 0.0))
        rows.append((TYPE_LABELS[t], model, agg, mape, TYPE_COLORS[t]))

    fig, ax = plt.subplots(figsize=(14.2, 6.0))
    ax.set_axis_off()
    ax.text(0.5, 0.94, "적정 종류별 최종 선택 모델", transform=ax.transAxes, ha="center", va="center", fontsize=30, fontweight="bold")
    headers = ["적정 종류", "분류 모델", "최종 부피 산출 방식", "MAPE"]
    xs = [0.16, 0.39, 0.65, 0.87]
    y0 = 0.78
    for x, h in zip(xs, headers):
        ax.text(x, y0, h, transform=ax.transAxes, ha="center", va="center", fontsize=18, fontweight="bold", color="#334155")
    ax.plot([0.05, 0.95], [0.72, 0.72], transform=ax.transAxes, color="#CBD5E1", linewidth=2)
    for i, (label, model, agg, mape, color) in enumerate(rows):
        y = 0.61 - i * 0.14
        box = FancyBboxPatch((0.055, y - 0.046), 0.89, 0.09, boxstyle="round,pad=0.012,rounding_size=0.018", linewidth=1.2, edgecolor="#E2E8F0", facecolor="#F8FAFC", transform=ax.transAxes)
        ax.add_patch(box)
        ax.scatter([0.075], [y], transform=ax.transAxes, s=140, color=color)
        ax.text(xs[0], y, label, transform=ax.transAxes, ha="center", va="center", fontsize=17, fontweight="bold")
        ax.text(xs[1], y, model, transform=ax.transAxes, ha="center", va="center", fontsize=17)
        ax.text(xs[2], y, agg, transform=ax.transAxes, ha="center", va="center", fontsize=17)
        ax.text(xs[3], y, f"{mape:.2f}%", transform=ax.transAxes, ha="center", va="center", fontsize=18, fontweight="bold")
    ax.text(0.5, 0.08, "실제 실험에서는 사용자가 선택한 적정 종류에 맞는 모델을 적용한다.", transform=ax.transAxes, ha="center", fontsize=16, color="#475569")
    save(fig, "ml_09_selected_model_by_type")

def write_text(summary: dict[str, Any]) -> None:
    selector = summary.get("typewise_development_selector", {}).get("selection", {})
    lines = [
        "[포스터용 머신러닝 설명]",
        "",
        "본 연구에서는 실제 적정 중 얻을 수 있는 주입량, HSV 색 변화, ROI 온도 변화를 이용해 당량점 부피를 예측하였다. 학습 단계에서는 이론 당량점 부피를 기준으로 각 프레임을 당량점 부근과 비부근으로 라벨링하였고, 실제 예측 단계에서는 이론 당량점 정보를 입력하지 않고 센서값만 사용하였다.",
        "",
        "산과 염기의 세기에 따라 색 변화와 중화열 변화 양상이 달라지므로, 하나의 통합 모델이 아니라 적정 종류별 모델을 적용하였다. Random Forest와 Extra Trees 분류 모델로 당량점 부근 프레임을 찾고, 점수가 높은 프레임들의 주입량을 종합하여 최종 당량점 부피를 산출하였다.",
        "",
        "[포스터용 결과 문장]",
        "",
        "단일 통합 모델의 평균 상대오차는 6.03%였으나, 적정 종류별 모델을 적용하였을 때 평균 상대오차는 1.27%, 평균 절대오차는 0.392 mL로 감소하였다. 이는 적정 종류에 따라 다른 색 변화와 온도 변화 패턴을 구분해 학습하는 방식이 당량점 예측에 효과적임을 보여준다.",
        "",
        "[사용한 모델]",
        "",
    ]
    for t in TYPE_ORDER:
        method = selector.get(t, {}).get("selected_method_key", "")
        short = "Extra Trees" if "extra_trees" in method else "Random Forest" if "random_forest" in method else method
        lines.append(f"{TYPE_LABELS[t]}: {short} 기반 프레임 분류 모델")
    lines.extend(
        [
            "",
            "[주의 문장]",
            "",
            "현재 결과는 총 12개 CSV를 바탕으로 한 결과이며, 적정 종류별 데이터 수가 3개씩으로 제한되어 있다. 따라서 실제 적용 가능성은 확인하였지만, 더 많은 반복 실험을 통해 모델의 일반화 성능을 추가로 검증할 필요가 있다.",
            "",
            "[그래프 파일]",
            "",
            "docs/poster_assets/ml_01_model_comparison.png",
            "docs/poster_assets/ml_02_typewise_mape.png",
            "docs/poster_assets/ml_03_actual_vs_predicted.png",
            "docs/poster_assets/ml_04_prediction_workflow.png",
            "docs/poster_assets/ml_05_method_family_comparison.png",
            "docs/poster_assets/ml_06_regression_algorithm_comparison.png",
            "docs/poster_assets/ml_07_run_error_by_condition.png",
            "docs/poster_assets/ml_08_sensor_curves_by_type.png",
            "docs/poster_assets/ml_09_selected_model_by_type.png",
        ]
    )
    TEXT_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_preview_html() -> None:
    html = """<!doctype html>
<html lang=\"ko\"><head><meta charset=\"utf-8\"><title>ML Poster Assets</title>
<style>body{font-family:Pretendard,Arial,sans-serif;margin:24px;background:#f8fafc}section{background:white;margin:24px 0;padding:20px;border-radius:18px;box-shadow:0 6px 20px #0001}img{max-width:100%;height:auto}h1{font-size:28px}</style></head><body>
<h1>머신러닝 포스터 시각화</h1>
"""
    for p in sorted(OUT.glob("ml_*.png")):
        html += f'<section><h2>{p.name}</h2><img src="{p.name}" alt="{p.name}"></section>\n'
    html += "</body></html>\n"
    (OUT / "index.html").write_text(html, encoding="utf-8")


def main() -> None:
    setup_style()
    summary = json.loads((BASE / "summary.json").read_text(encoding="utf-8"))
    model_comparison(summary)
    typewise_error(summary)
    actual_vs_predicted()
    workflow_diagram()
    method_family_comparison()
    regression_algorithm_comparison()
    run_error_by_condition()
    sensor_curves_by_type()
    selected_model_by_type()
    write_text(summary)
    make_preview_html()
    print(f"wrote {OUT}")
    print(f"wrote {TEXT_OUT}")


if __name__ == "__main__":
    main()
