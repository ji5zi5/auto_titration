#!/usr/bin/env python3
"""Generate extra poster-ready analysis figures for the auto titration project."""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

OUT_DIR = Path("docs/poster_visuals")
ML_DIR = Path("data/ml/curve_equivalence_current")
SUMMARY_JSON = ML_DIR / "curve_equivalence_summary.json"
SUMMARY_CSV = ML_DIR / "curve_equivalence_summary.csv"
FEATURE_IMPORTANCE = ML_DIR / "feature_importance.csv"
FEATURE_SET = ML_DIR / "feature_set_comparison.csv"
MODEL_COMPARE = ML_DIR / "model_algorithm_comparison.csv"

TYPE_LABELS = {
    "strong_acid_strong_base": "강산-강염기",
    "strong_acid_weak_base": "강산-약염기",
    "weak_acid_strong_base": "약산-강염기",
    "weak_acid_weak_base": "약산-약염기",
}
TYPE_ORDER = list(TYPE_LABELS.keys())
CONC_ORDER = [0.1, 0.15, 0.2]

FEATURE_LABELS = {
    "candidate_fraction_of_run": "후보 위치\n(진행 비율)",
    "candidate_volume_ml": "후보 주입량",
    "source_is_color": "색 후보 여부",
    "source_is_thermal": "열 후보 여부",
    "source_is_fusion": "융합 후보 여부",
    "thermal_peak_slope": "온도 변화\n기울기",
    "thermal_raw_peak_slope": "raw 온도\n기울기",
    "thermal_p95_peak_slope": "상위 온도\n기울기",
    "thermal_pre_post_delta": "당량점 전후\n온도 차",
    "visible_peak_slope": "색 변화\n기울기",
    "visible_hsv_peak_slope": "HSV 변화\n기울기",
    "visible_pre_post_delta": "당량점 전후\n색 차",
    "nearest_color_candidate_distance_ml": "색 후보와\n거리",
    "nearest_thermal_candidate_distance_ml": "열 후보와\n거리",
    "nearest_fusion_candidate_distance_ml": "융합 후보와\n거리",
    "visible_thermal_delta_agreement": "색·열 변화\n일치도",
    "fusion_peak_score": "융합 후보\n점수",
    "candidate_local_density_1p0ml": "1 mL 주변\n후보 밀도",
    "run_volume_max_ml": "최대 주입량",
    "run_duration_s": "실험 시간",
}

FEATURE_SET_LABELS = {
    "thermal_basic": "온도",
    "color_expanded": "색 변화",
    "current_fusion": "색 변화+온도",
    "fusion_expanded": "색 변화+온도 세부특징",
}


def setup_font() -> None:
    for p in [
        Path.home() / ".local/share/fonts/Pretendard/Pretendard-Regular.ttf",
        Path.home() / ".local/share/fonts/Pretendard/PretendardVariable.ttf",
    ]:
        if p.exists():
            font_manager.fontManager.addfont(str(p))
            break
    plt.rcParams.update(
        {
            "font.family": "Pretendard",
            "font.size": 20,
            "axes.titlesize": 27,
            "axes.labelsize": 22,
            "xtick.labelsize": 17,
            "ytick.labelsize": 17,
            "legend.fontsize": 18,
            "figure.titlesize": 34,
            "savefig.dpi": 220,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#111827",
            "axes.linewidth": 1.3,
        }
    )


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def fnum(v) -> float:
    try:
        if v is None or v == "":
            return math.nan
        return float(v)
    except Exception:
        return math.nan


def style_ax(ax, grid=True) -> None:
    if grid:
        ax.grid(True, color="#E5E7EB", linewidth=1.0, alpha=0.9, axis="y")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def selected_feature_sets() -> dict[str, str]:
    data = json.loads(SUMMARY_JSON.read_text(encoding="utf-8"))
    return {t: payload.get("selected_model", {}).get("feature_set", "") for t, payload in data.get("types", {}).items()}


def selected_predictions() -> list[dict[str, object]]:
    data = json.loads(SUMMARY_JSON.read_text(encoding="utf-8"))
    preds = []
    for t, payload in data.get("types", {}).items():
        selected = payload.get("selected_model", {}).get("feature_set", "")
        for fold in payload.get("folds", []):
            if fold.get("feature_set") != selected:
                continue
            for p in fold.get("predictions", []):
                q = dict(p)
                q["type_label"] = TYPE_LABELS.get(t, t)
                preds.append(q)
    preds.sort(key=lambda p: (TYPE_ORDER.index(str(p.get("titration_type"))) if p.get("titration_type") in TYPE_ORDER else 99, fnum(p.get("held_out_concentration_m"))))
    return preds


def plot_feature_importance() -> Path:
    selected = selected_feature_sets()
    acc: dict[str, list[float]] = defaultdict(list)
    for r in read_rows(FEATURE_IMPORTANCE):
        t = r.get("titration_type", "")
        if r.get("feature_set") != selected.get(t):
            continue
        acc[r.get("feature", "")].append(fnum(r.get("importance")))
    items = []
    for feat, vals in acc.items():
        vals = [v for v in vals if math.isfinite(v)]
        if vals:
            items.append((feat, float(np.mean(vals))))
    items.sort(key=lambda x: x[1], reverse=True)
    top = items[:10]
    labels = [FEATURE_LABELS.get(k, k.replace("_", "\n")) for k, _ in top][::-1]
    vals = [v for _, v in top][::-1]
    fig, ax = plt.subplots(figsize=(14, 10), constrained_layout=True)
    bars = ax.barh(labels, vals, color="#2563EB")
    ax.set_title("최종 모델에서 중요하게 사용된 입력값", fontweight="bold")
    ax.set_xlabel("평균 feature importance")
    ax.set_xlim(0, max(vals) * 1.22 if vals else 1)
    for b, v in zip(bars, vals):
        ax.text(v + max(vals) * 0.025, b.get_y() + b.get_height() / 2, f"{v:.2f}", va="center", fontweight="bold")
    style_ax(ax, grid=False)
    path = OUT_DIR / "08_feature_importance_top10.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_feature_set_heatmap() -> Path:
    wanted = ["thermal_basic", "color_expanded", "current_fusion", "fusion_expanded"]
    rows = read_rows(FEATURE_SET)
    mat = np.full((len(TYPE_ORDER), len(wanted)), np.nan)
    for r in rows:
        t = r.get("titration_type", "")
        fs = r.get("feature_set", "")
        if t in TYPE_ORDER and fs in wanted:
            mat[TYPE_ORDER.index(t), wanted.index(fs)] = fnum(r.get("mae_ml"))
    fig, ax = plt.subplots(figsize=(13, 8), constrained_layout=True)
    im = ax.imshow(mat, cmap="YlOrRd", aspect="auto", vmin=0, vmax=np.nanpercentile(mat, 90))
    ax.set_title("입력값 조합별 당량점 예측 오차", fontweight="bold")
    ax.set_xticks(range(len(wanted)), [FEATURE_SET_LABELS.get(x, x) for x in wanted])
    ax.set_yticks(range(len(TYPE_ORDER)), [TYPE_LABELS[t] for t in TYPE_ORDER])
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            v = mat[i, j]
            if math.isfinite(v):
                ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=17, fontweight="bold", color="#111827")
    cbar = fig.colorbar(im, ax=ax, shrink=0.85)
    cbar.set_label("MAE (mL)")
    path = OUT_DIR / "09_feature_set_mae_heatmap.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_concentration_error_heatmap() -> Path:
    selected = selected_feature_sets()
    mat = np.full((len(TYPE_ORDER), len(CONC_ORDER)), np.nan)
    for r in read_rows(SUMMARY_CSV):
        t = r.get("titration_type", "")
        if r.get("feature_set") != selected.get(t):
            continue
        c = fnum(r.get("held_out_concentration_m"))
        for idx, cc in enumerate(CONC_ORDER):
            if abs(c - cc) < 1e-9 and t in TYPE_ORDER:
                mat[TYPE_ORDER.index(t), idx] = fnum(r.get("mae_ml"))
    fig, ax = plt.subplots(figsize=(11, 9), constrained_layout=True)
    im = ax.imshow(mat, cmap="YlGnBu", aspect="auto", vmin=0, vmax=max(6, np.nanmax(mat)))
    ax.set_title("농도 조건별 예측 오차", fontweight="bold")
    ax.set_xticks(range(len(CONC_ORDER)), [f"{c:g} M" for c in CONC_ORDER])
    ax.set_yticks(range(len(TYPE_ORDER)), [TYPE_LABELS[t] for t in TYPE_ORDER])
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            v = mat[i, j]
            if math.isfinite(v):
                ax.text(j, i, f"{v:.2f}\nmL", ha="center", va="center", fontsize=18, fontweight="bold", color="#111827")
    cbar = fig.colorbar(im, ax=ax, shrink=0.82)
    cbar.set_label("절대오차 (mL)")
    path = OUT_DIR / "10_concentration_error_heatmap.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_actual_predicted_grouped_bars() -> Path:
    preds = selected_predictions()
    labels = [f"{p['type_label']}\n{fnum(p.get('held_out_concentration_m')):g}M" for p in preds]
    actual = np.array([fnum(p.get("actual_equivalence_volume_ml")) for p in preds])
    predicted = np.array([fnum(p.get("predicted_equivalence_volume_ml")) for p in preds])
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(19, 10), constrained_layout=True)
    w = 0.36
    ax.bar(x - w / 2, actual, w, color="#111827", label="이론 당량점")
    ax.bar(x + w / 2, predicted, w, color="#F59E0B", label="ML 예측")
    ax.set_title("실험별 이론 당량점과 ML 예측 부피", fontweight="bold")
    ax.set_ylabel("당량점 부피 (mL)")
    ax.set_xticks(x, labels)
    ax.legend(frameon=False, loc="upper left")
    ax.set_ylim(0, max(np.nanmax(actual), np.nanmax(predicted)) * 1.18)
    for xi, a, p in zip(x, actual, predicted):
        ax.text(xi + w / 2, p + 0.7, f"{p:.1f}", ha="center", fontsize=14, fontweight="bold")
    style_ax(ax)
    path = OUT_DIR / "11_actual_vs_predicted_grouped_bars.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_success_rates() -> Path:
    rows = [r for r in read_rows(MODEL_COMPARE) if r.get("scope") == "overall" and r.get("model") == "Extra Trees Regression"]
    r = rows[0]
    labels = ["±0.5 mL", "±1.0 mL", "±2%", "±5%"]
    vals = [fnum(r.get("within_0.5ml_rate")), fnum(r.get("within_1.0ml_rate")), fnum(r.get("within_2pct_rate")), fnum(r.get("within_5pct_rate"))]
    vals = np.array(vals) * 100
    fig, ax = plt.subplots(figsize=(12, 8), constrained_layout=True)
    colors = ["#EF4444", "#F97316", "#2563EB", "#10B981"]
    bars = ax.bar(labels, vals, color=colors, width=0.58)
    ax.set_title("최종 모델 허용오차별 성공률", fontweight="bold")
    ax.set_ylabel("성공률 (%)")
    ax.set_ylim(0, 100)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 3, f"{v:.1f}%", ha="center", fontweight="bold", fontsize=22)
    style_ax(ax)
    path = OUT_DIR / "12_success_rate_summary.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_sensor_ablation_overall() -> Path:
    wanted = ["thermal_basic", "color_expanded", "current_fusion", "fusion_expanded"]
    rows = read_rows(FEATURE_SET)
    acc = defaultdict(list)
    for r in rows:
        fs = r.get("feature_set", "")
        if fs in wanted:
            acc[fs].append(fnum(r.get("mae_ml")))
    vals = [float(np.nanmean(acc[fs])) for fs in wanted]
    labels = ["온도", "색 변화", "색 변화+온도", "색 변화+온도 세부특징"]
    fig, ax = plt.subplots(figsize=(16, 9), constrained_layout=True)
    colors = ["#0EA5E9", "#E11D48", "#2563EB", "#7C3AED"]
    bars = ax.bar(labels, vals, color=colors, width=0.62)
    ax.set_title("입력값 조합에 따른 예측 오차", fontweight="bold")
    ax.set_ylabel("평균 MAE (mL)")
    ax.set_ylim(0, max(vals) * 1.24)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + max(vals) * 0.035, f"{v:.1f}", ha="center", fontweight="bold", fontsize=19)
    style_ax(ax)
    path = OUT_DIR / "13_sensor_ablation_overall.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def update_readme(paths: list[Path]) -> None:
    readme = OUT_DIR / "README.txt"
    desc = {
        "08_feature_importance_top10.png": "최종 Extra Trees 모델에서 중요도가 높게 나온 입력값 상위 10개.",
        "09_feature_set_mae_heatmap.png": "입력 feature set별 MAE 히트맵. 색/열/주입량 조합과 sensor-only/no-progress 비교.",
        "10_concentration_error_heatmap.png": "적정 종류와 농도 조건별 예측 오차 히트맵.",
        "11_actual_vs_predicted_grouped_bars.png": "12개 실험별 이론 당량점과 ML 예측 당량점 부피 비교.",
        "12_success_rate_summary.png": "최종 모델의 허용오차별 성공률 요약.",
        "13_sensor_ablation_overall.png": "센서 조합과 주입량/진행 정보가 예측 성능에 미친 영향 비교.",
    }
    text = readme.read_text(encoding="utf-8") if readme.exists() else "포스터용 시각화 파일 목록\n"
    marker = "\n추가 분석 그림\n"
    if marker in text:
        text = text.split(marker)[0].rstrip() + "\n"
    lines = [text.rstrip(), "", "추가 분석 그림"]
    for p in paths:
        lines.append(f"{p.name}\t{desc.get(p.name, '')}")
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    setup_font()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = [
        plot_feature_importance(),
        plot_feature_set_heatmap(),
        plot_concentration_error_heatmap(),
        plot_actual_predicted_grouped_bars(),
        plot_success_rates(),
        plot_sensor_ablation_overall(),
    ]
    update_readme(paths)
    for p in paths:
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
