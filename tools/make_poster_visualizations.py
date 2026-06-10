#!/usr/bin/env python3
"""Create poster-ready visualizations from collected titration CSV data.

Outputs large-text PNG figures using Pretendard when available.
"""
from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

DATA_DIR = Path("머신러닝용 파일모음")
ML_SUMMARY = Path("data/ml/curve_equivalence_current/curve_equivalence_summary.json")
MODEL_COMPARE = Path("data/ml/curve_equivalence_current/model_algorithm_comparison.csv")
TYPEWISE_METRICS = Path("data/ml/curve_equivalence_current/typewise_run_metrics.csv")
OUT_DIR = Path("docs/poster_visuals")
RUN_DIR = OUT_DIR / "run_curves"

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
MODEL_ORDER = ["Ridge Regression", "KNN Regression", "Random Forest Regression", "Extra Trees Regression"]
COLORS = {
    "color": "#E11D48",
    "thermal": "#0EA5E9",
    "actual": "#111827",
    "predicted": "#F59E0B",
    "good": "#10B981",
    "warn": "#F97316",
    "bad": "#EF4444",
    "grid": "#E5E7EB",
}


def setup_font() -> None:
    candidates = [
        Path.home() / ".local/share/fonts/Pretendard/Pretendard-Regular.ttf",
        Path.home() / ".local/share/fonts/Pretendard/Pretendard-Regular.otf",
        Path.home() / ".local/share/fonts/Pretendard/PretendardVariable.ttf",
    ]
    for path in candidates:
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            break
    plt.rcParams.update(
        {
            "font.family": "Pretendard",
            "font.size": 20,
            "axes.titlesize": 26,
            "axes.labelsize": 22,
            "xtick.labelsize": 17,
            "ytick.labelsize": 17,
            "legend.fontsize": 17,
            "figure.titlesize": 36,
            "axes.linewidth": 1.4,
            "axes.edgecolor": "#111827",
            "savefig.dpi": 220,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )


def num(value: object) -> float:
    try:
        if value is None or value == "":
            return math.nan
        return float(value)
    except Exception:
        return math.nan


def clean_finite(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mask = np.isfinite(x) & np.isfinite(y)
    return x[mask], y[mask]


def smooth(y: np.ndarray, window: int = 5) -> np.ndarray:
    if y.size < 3:
        return y
    window = max(1, min(window, y.size))
    if window <= 1:
        return y
    kernel = np.ones(window) / window
    pad = window // 2
    filled = np.array(y, dtype=float)
    if not np.isfinite(filled).all():
        finite = np.isfinite(filled)
        if finite.any():
            idx = np.arange(filled.size)
            filled[~finite] = np.interp(idx[~finite], idx[finite], filled[finite])
    padded = np.pad(filled, (pad, window - 1 - pad), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def rolling_median(y: np.ndarray, window: int = 9) -> np.ndarray:
    out = np.array(y, dtype=float)
    if out.size < 3:
        return out
    window = max(1, min(window, out.size))
    half = window // 2
    result = np.empty_like(out)
    for i in range(out.size):
        lo = max(0, i - half)
        hi = min(out.size, i + half + 1)
        vals = out[lo:hi]
        vals = vals[np.isfinite(vals)]
        result[i] = np.nan if vals.size == 0 else float(np.nanmedian(vals))
    return result


def binned_series(x: np.ndarray, y: np.ndarray, *, bin_width: float = 0.65) -> tuple[np.ndarray, np.ndarray]:
    x = np.array(x, dtype=float)
    y = np.array(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x = x[mask]
    y = y[mask]
    if x.size < 3:
        return x, y
    bins = np.floor(x / bin_width).astype(int)
    bx: list[float] = []
    by: list[float] = []
    for b in sorted(set(int(v) for v in bins)):
        vals = y[bins == b]
        xs = x[bins == b]
        if vals.size:
            bx.append(float(np.nanmean(xs)))
            by.append(float(np.nanmedian(vals)))
    return np.array(bx), np.array(by)


def stable_hsv_change(h: np.ndarray, sat: np.ndarray, val: np.ndarray) -> np.ndarray:
    h = np.array(h, dtype=float)
    sat = np.array(sat, dtype=float)
    val = np.array(val, dtype=float)
    valid = np.isfinite(h) & np.isfinite(sat) & np.isfinite(val)
    if not valid.any():
        return np.full_like(h, np.nan, dtype=float)
    first = np.where(valid)[0][: min(12, int(valid.sum()))]
    h0 = float(np.nanmedian(h[first]))
    s0 = float(np.nanmedian(sat[first]))
    v0 = float(np.nanmedian(val[first]))
    hue_delta = np.abs(((h - h0 + 180.0) % 360.0) - 180.0) / 180.0
    sat_delta = sat - s0
    val_delta = val - v0
    metric = np.sqrt(hue_delta**2 + (1.8 * sat_delta) ** 2 + (0.8 * val_delta) ** 2)
    metric[~valid] = np.nan
    return smooth(rolling_median(metric, 9), 7)


def unwrap_hue_deg(h: np.ndarray) -> np.ndarray:
    h = np.array(h, dtype=float)
    valid = np.isfinite(h)
    if valid.sum() < 2:
        return h
    out = h.copy()
    idx = np.where(valid)[0]
    unwrapped = np.rad2deg(np.unwrap(np.deg2rad(h[idx])))
    out[idx] = unwrapped
    return out


def normalize_actual_channel(y: np.ndarray) -> np.ndarray:
    # Actual channel visualization: keeps up/down trend instead of distance-from-start only.
    return robust_normalize(smooth(rolling_median(y, 9), 7))


def robust_normalize(y: np.ndarray) -> np.ndarray:
    out = np.array(y, dtype=float)
    finite = np.isfinite(out)
    if not finite.any():
        return out
    vals = out[finite]
    lo = np.nanpercentile(vals, 5)
    hi = np.nanpercentile(vals, 95)
    if abs(hi - lo) < 1e-12:
        lo = np.nanmin(vals)
        hi = np.nanmax(vals)
    if abs(hi - lo) < 1e-12:
        out[finite] = 0.0
        return out
    out = (out - lo) / (hi - lo)
    out = np.clip(out, 0.0, 1.0)
    return out


def first_valid_baseline(vals: np.ndarray, limit: int = 10) -> float:
    good = vals[np.isfinite(vals) & (np.abs(vals) > 1e-12)]
    good = good[good > 5.0]  # thermal Celsius should not be zero/blank.
    if good.size == 0:
        return 0.0
    return float(np.nanmedian(good[: min(limit, good.size)]))


@dataclass
class RunData:
    path: Path
    basename: str
    titration_type: str
    type_label: str
    concentration: float
    equivalence_ml: float
    x_ml: np.ndarray
    x_norm: np.ndarray
    color_signal: np.ndarray
    hue_norm: np.ndarray
    sat_norm: np.ndarray
    value_norm: np.ndarray
    thermal_delta_c: np.ndarray
    thermal_norm: np.ndarray
    color_norm: np.ndarray
    sync_offset_ms: np.ndarray
    row_count: int
    duration_s: float
    max_volume_ml: float

    @property
    def short_label(self) -> str:
        return f"{self.type_label} {self.concentration:g}M"


def read_run(path: Path) -> RunData:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"empty CSV: {path}")
    first = rows[0]
    titration_type = first.get("titration_type", "")
    concentration = num(first.get("sample_concentration_M"))
    equivalence = num(first.get("theoretical_equivalence_volume_ml"))
    x = np.array([num(r.get("injected_volume_ml")) for r in rows], dtype=float)
    # Poster graph uses a stable color-state metric, not frame-to-frame delta.
    # Frame-to-frame delta is useful for candidate detection but looks too jittery as a poster curve.
    h_mean = np.array([num(r.get("visible_H_mean")) for r in rows], dtype=float)
    s_mean = np.array([num(r.get("visible_S_mean")) for r in rows], dtype=float)
    v_mean = np.array([num(r.get("visible_V_mean")) for r in rows], dtype=float)
    color = stable_hsv_change(h_mean, s_mean, v_mean)
    thermal_avg = np.array([num(r.get("thermal_roi_avg")) for r in rows], dtype=float)
    baseline = first_valid_baseline(thermal_avg)
    thermal_delta = thermal_avg - baseline
    thermal_delta[(~np.isfinite(thermal_avg)) | (thermal_avg < 5.0)] = math.nan
    sync = np.array([num(r.get("sync_offset_ms")) for r in rows], dtype=float)
    elapsed = np.array([num(r.get("csv_recording_elapsed_s")) for r in rows], dtype=float)
    duration = float(np.nanmax(elapsed)) if np.isfinite(elapsed).any() else float(np.nanmax(x) / (num(first.get("pump_run_rate_ml_per_s")) or 1.0))
    order = np.argsort(np.nan_to_num(x, nan=-1.0))
    x = x[order]
    color = color[order]
    thermal_delta = thermal_delta[order]
    sync = sync[order]
    x_norm = x / equivalence if np.isfinite(equivalence) and equivalence > 0 else x
    color_norm = robust_normalize(color)
    thermal_norm = robust_normalize(smooth(rolling_median(thermal_delta, 9), 7))
    return RunData(
        path=path,
        basename=path.name,
        titration_type=titration_type,
        type_label=TYPE_LABELS.get(titration_type, titration_type),
        concentration=concentration,
        equivalence_ml=equivalence,
        x_ml=x,
        x_norm=x_norm,
        color_signal=color,
        hue_norm=normalize_actual_channel(unwrap_hue_deg(h_mean)),
        sat_norm=normalize_actual_channel(s_mean),
        value_norm=normalize_actual_channel(v_mean),
        thermal_delta_c=thermal_delta,
        thermal_norm=thermal_norm,
        color_norm=color_norm,
        sync_offset_ms=sync,
        row_count=len(rows),
        duration_s=duration,
        max_volume_ml=float(np.nanmax(x)) if np.isfinite(x).any() else math.nan,
    )


def load_runs() -> list[RunData]:
    files = sorted(DATA_DIR.glob("*.csv"))
    runs = [read_run(path) for path in files]
    runs.sort(key=lambda r: (TYPE_ORDER.index(r.titration_type) if r.titration_type in TYPE_ORDER else 99, r.concentration))
    return runs


def load_predictions() -> dict[str, dict[str, float | str]]:
    if not ML_SUMMARY.exists():
        return {}
    data = json.loads(ML_SUMMARY.read_text(encoding="utf-8"))
    out: dict[str, dict[str, float | str]] = {}
    for titration_type, payload in data.get("types", {}).items():
        selected = payload.get("selected_model", {}).get("feature_set", "")
        for fold in payload.get("folds", []):
            if fold.get("feature_set") != selected:
                continue
            for pred in fold.get("predictions", []):
                base = Path(str(pred.get("run_path", ""))).name
                out[base] = {
                    "predicted": num(pred.get("predicted_equivalence_volume_ml")),
                    "actual": num(pred.get("actual_equivalence_volume_ml")),
                    "abs_error": num(pred.get("absolute_error_ml")),
                    "signed_error": num(pred.get("signed_error_ml")),
                    "percent_error": num(pred.get("absolute_error_percent_of_equivalence")),
                    "feature_set": str(pred.get("feature_set", "")),
                    "candidate_source": str(pred.get("chosen_candidate_source", "")),
                }
    return out


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def style_ax(ax, grid: bool = True) -> None:
    if grid:
        ax.grid(True, color=COLORS["grid"], linewidth=1.0, alpha=0.9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def safe_file_label(name: str) -> str:
    match = re.search(r"session-(\d+)", name)
    return f"session_{match.group(1)}" if match else re.sub(r"\W+", "_", name)


def plot_all_runs_hue_thermal_grid(runs: list[RunData], predictions: dict[str, dict[str, float | str]]) -> Path:
    fig, axes = plt.subplots(4, 3, figsize=(22, 26), constrained_layout=False)
    fig.suptitle("수집 데이터 전체: H 색상과 열화상 온도 변화", fontweight="bold", y=0.985, fontsize=34)
    for ax, run in zip(axes.flat, runs):
        x = run.x_ml
        hx, hy = binned_series(x, run.hue_norm, bin_width=0.65)
        tx, ty = binned_series(x, run.thermal_norm, bin_width=0.65)
        ax.plot(hx, hy, color=COLORS["color"], linewidth=3.4, label="H 색상")
        ax.plot(tx, ty, color=COLORS["thermal"], linewidth=3.4, label="온도 변화")
        ax.axvline(run.equivalence_ml, color=COLORS["actual"], linewidth=2.8, linestyle="--", label="이론 당량점")
        ax.set_title(run.short_label, fontweight="bold", pad=10)
        ax.set_xlim(0, max(float(np.nanmax(x)), run.equivalence_ml) * 1.04)
        ax.set_ylim(-0.05, 1.08)
        ax.set_xlabel("주입량 (mL)")
        ax.set_ylabel("정규화 신호")
        style_ax(ax)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.subplots_adjust(top=0.93, bottom=0.065, hspace=0.55, wspace=0.28)
    fig.legend(handles, labels, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 0.012), fontsize=22)
    path = OUT_DIR / "01c_all_runs_hue_thermal_grid.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_all_runs_hsv_channels_grid(runs: list[RunData], predictions: dict[str, dict[str, float | str]]) -> Path:
    fig, axes = plt.subplots(4, 3, figsize=(22, 26), constrained_layout=False)
    fig.suptitle("수집 데이터 전체: 실제 HSV 색 성분 변화", fontweight="bold", y=0.985, fontsize=34)
    for ax, run in zip(axes.flat, runs):
        x = run.x_ml
        hx, hy = binned_series(x, run.hue_norm, bin_width=0.65)
        sx, sy = binned_series(x, run.sat_norm, bin_width=0.65)
        vx, vy = binned_series(x, run.value_norm, bin_width=0.65)
        ax.plot(hx, hy, color="#E11D48", linewidth=3.0, label="H 색상")
        ax.plot(sx, sy, color="#7C3AED", linewidth=3.0, label="S 채도")
        ax.plot(vx, vy, color="#0EA5E9", linewidth=3.0, label="V 명도")
        ax.axvline(run.equivalence_ml, color=COLORS["actual"], linewidth=2.8, linestyle="--", label="이론 당량점")
        ax.set_title(run.short_label, fontweight="bold", pad=10)
        ax.set_xlim(0, max(float(np.nanmax(x)), run.equivalence_ml) * 1.04)
        ax.set_ylim(-0.05, 1.08)
        ax.set_xlabel("주입량 (mL)")
        ax.set_ylabel("정규화 성분값")
        style_ax(ax)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.subplots_adjust(top=0.93, bottom=0.065, hspace=0.55, wspace=0.28)
    fig.legend(handles, labels, loc="lower center", ncol=5, frameon=False, bbox_to_anchor=(0.5, 0.012), fontsize=22)
    path = OUT_DIR / "01b_all_runs_hsv_channels_grid.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_all_runs_grid(runs: list[RunData], predictions: dict[str, dict[str, float | str]]) -> Path:
    fig, axes = plt.subplots(4, 3, figsize=(22, 26), constrained_layout=False)
    fig.suptitle("수집 데이터 전체: 색 변화와 열화상 변화", fontweight="bold", y=0.985, fontsize=34)
    for ax, run in zip(axes.flat, runs):
        x = run.x_ml
        cx, cy = binned_series(x, run.color_norm, bin_width=0.65)
        tx, ty = binned_series(x, run.thermal_norm, bin_width=0.65)
        ax.plot(cx, cy, color=COLORS["color"], linewidth=3.2, label="색 변화")
        ax.plot(tx, ty, color=COLORS["thermal"], linewidth=3.2, label="온도 변화")
        ax.axvline(run.equivalence_ml, color=COLORS["actual"], linewidth=2.8, linestyle="--", label="이론 당량점")
        ax.set_title(run.short_label, fontweight="bold", pad=10)
        ax.set_xlim(0, max(float(np.nanmax(x)), run.equivalence_ml) * 1.04)
        ax.set_ylim(-0.05, 1.08)
        ax.set_xlabel("주입량 (mL)")
        ax.set_ylabel("정규화 신호")
        style_ax(ax)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.subplots_adjust(top=0.93, bottom=0.065, hspace=0.55, wspace=0.28)
    fig.legend(handles, labels, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 0.012), fontsize=22)
    path = OUT_DIR / "01_all_runs_sensor_curves_grid.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_type_mean_curves(runs: list[RunData]) -> Path:
    fig, axes = plt.subplots(2, 2, figsize=(20, 15), constrained_layout=True)
    fig.suptitle("적정 종류별 평균 신호 변화", fontweight="bold")
    common_x = np.linspace(0, 1.35, 220)
    for ax, titration_type in zip(axes.flat, TYPE_ORDER):
        group = [r for r in runs if r.titration_type == titration_type]
        color_curves = []
        thermal_curves = []
        for run in group:
            x, c = binned_series(run.x_norm, run.hue_norm, bin_width=0.025)
            if x.size >= 2:
                order = np.argsort(x)
                ux, idx = np.unique(x[order], return_index=True)
                if ux.size >= 2:
                    color_curves.append(np.interp(common_x, ux, c[order][idx], left=np.nan, right=np.nan))
            x2, t2 = binned_series(run.x_norm, run.thermal_norm, bin_width=0.025)
            if x2.size >= 2:
                order = np.argsort(x2)
                ux, idx = np.unique(x2[order], return_index=True)
                if ux.size >= 2:
                    thermal_curves.append(np.interp(common_x, ux, t2[order][idx], left=np.nan, right=np.nan))
        if color_curves:
            color_mean = np.nanmean(np.vstack(color_curves), axis=0)
            ax.plot(common_x, color_mean, color=COLORS["color"], linewidth=4, label="평균 H 색상")
        if thermal_curves:
            thermal_mean = np.nanmean(np.vstack(thermal_curves), axis=0)
            ax.plot(common_x, thermal_mean, color=COLORS["thermal"], linewidth=4, label="평균 온도 변화")
        ax.axvline(1.0, color=COLORS["actual"], linewidth=3, linestyle="--", label="이론 당량점")
        ax.set_title(TYPE_LABELS[titration_type], fontweight="bold")
        ax.set_xlabel("주입량 / 이론 당량점")
        ax.set_ylabel("정규화 신호")
        ax.set_xlim(0, 1.35)
        ax.set_ylim(-0.05, 1.05)
        style_ax(ax)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.02), fontsize=22)
    path = OUT_DIR / "02_type_mean_sensor_curves.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_prediction_scatter(predictions: dict[str, dict[str, float | str]], runs: list[RunData]) -> Path:
    fig, ax = plt.subplots(figsize=(13, 11), constrained_layout=True)
    xs = []
    ys = []
    labels = []
    colors = []
    for run in runs:
        pred = predictions.get(run.basename)
        if not pred:
            continue
        actual = float(pred.get("actual", math.nan))
        predicted = float(pred.get("predicted", math.nan))
        if not (math.isfinite(actual) and math.isfinite(predicted)):
            continue
        xs.append(actual)
        ys.append(predicted)
        labels.append(f"{run.concentration:g}M")
        colors.append(TYPE_ORDER.index(run.titration_type))
    cmap = ["#2563EB", "#7C3AED", "#059669", "#EA580C"]
    for i, (x, y, label, ci) in enumerate(zip(xs, ys, labels, colors)):
        ax.scatter(x, y, s=220, color=cmap[ci], edgecolor="white", linewidth=2.5, zorder=3)
        ax.text(x + 0.25, y + 0.25, label, fontsize=16, fontweight="bold")
    lo = min(xs + ys) - 2
    hi = max(xs + ys) + 2
    ax.plot([lo, hi], [lo, hi], color=COLORS["actual"], linewidth=3, linestyle="--", label="완전 일치선")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("이론 당량점 (mL)")
    ax.set_ylabel("예측 당량점 (mL)")
    ax.set_title("이론 당량점과 예측 당량점 비교", fontweight="bold")
    style_ax(ax)
    # Legend by type.
    handles = [plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=cmap[i], markersize=16, label=TYPE_LABELS[t]) for i, t in enumerate(TYPE_ORDER)]
    handles.append(plt.Line2D([0], [0], color=COLORS["actual"], linestyle="--", linewidth=3, label="완전 일치선"))
    ax.legend(handles=handles, loc="upper left", frameon=True, facecolor="white", edgecolor="#E5E7EB")
    path = OUT_DIR / "03_prediction_actual_vs_predicted.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_typewise_mae() -> Path:
    rows = read_csv_rows(TYPEWISE_METRICS)
    rows = sorted(rows, key=lambda r: TYPE_ORDER.index(r["titration_type"]) if r.get("titration_type") in TYPE_ORDER else 99)
    labels = [TYPE_LABELS.get(r["titration_type"], r["titration_type"]) for r in rows]
    mae = np.array([num(r.get("mae_ml")) for r in rows], dtype=float)
    pct = np.array([num(r.get("mae_percent_of_equivalence")) for r in rows], dtype=float)
    fig, ax = plt.subplots(figsize=(15, 10), constrained_layout=True)
    bar_colors = ["#2563EB", "#7C3AED", "#059669", "#EA580C"]
    bars = ax.bar(labels, mae, color=bar_colors, width=0.62)
    ax.set_title("적정 종류별 당량점 예측 오차", fontweight="bold")
    ax.set_ylabel("MAE (mL)")
    ax.set_ylim(0, max(mae) * 1.35)
    for bar, m, p in zip(bars, mae, pct):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(mae) * 0.04, f"{m:.2f} mL\n{p:.1f}%", ha="center", va="bottom", fontsize=20, fontweight="bold")
    style_ax(ax)
    path = OUT_DIR / "04_typewise_mae_bar.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_algorithm_comparison() -> Path:
    rows = [r for r in read_csv_rows(MODEL_COMPARE) if r.get("scope") == "overall"]
    rows = sorted(rows, key=lambda r: MODEL_ORDER.index(r["model"]) if r.get("model") in MODEL_ORDER else 99)
    labels = [r["model"].replace(" Regression", "") for r in rows]
    mae = np.array([num(r.get("mae_ml")) for r in rows], dtype=float)
    rmse = np.array([num(r.get("rmse_ml")) for r in rows], dtype=float)
    fig, ax = plt.subplots(figsize=(15, 10), constrained_layout=True)
    x = np.arange(len(labels))
    width = 0.35
    ax.bar(x - width / 2, mae, width, color="#2563EB", label="MAE")
    ax.bar(x + width / 2, rmse, width, color="#F59E0B", label="RMSE")
    ax.set_xticks(x, labels)
    ax.set_ylabel("오차 (mL)")
    ax.set_title("회귀 알고리즘별 예측 오차 비교", fontweight="bold")
    ax.set_ylim(0, max(np.nanmax(rmse), np.nanmax(mae)) * 1.18)
    for xi, m in zip(x, mae):
        ax.text(xi - width / 2, m + max(rmse) * 0.02, f"{m:.2f}", ha="center", fontsize=18, fontweight="bold")
    for xi, r in zip(x, rmse):
        ax.text(xi + width / 2, r + max(rmse) * 0.02, f"{r:.2f}", ha="center", fontsize=18, fontweight="bold")
    ax.legend(frameon=False, loc="upper left")
    style_ax(ax)
    path = OUT_DIR / "05_model_algorithm_comparison.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_algorithm_comparison_zoom() -> Path:
    rows = [r for r in read_csv_rows(MODEL_COMPARE) if r.get("scope") == "overall" and r.get("model") != "Ridge Regression"]
    rows = sorted(rows, key=lambda r: MODEL_ORDER.index(r["model"]) if r.get("model") in MODEL_ORDER else 99)
    labels = [r["model"].replace(" Regression", "") for r in rows]
    mae = np.array([num(r.get("mae_ml")) for r in rows], dtype=float)
    rmse = np.array([num(r.get("rmse_ml")) for r in rows], dtype=float)
    fig, ax = plt.subplots(figsize=(13, 9), constrained_layout=True)
    x = np.arange(len(labels))
    width = 0.36
    ax.bar(x - width / 2, mae, width, color="#2563EB", label="MAE")
    ax.bar(x + width / 2, rmse, width, color="#F59E0B", label="RMSE")
    ax.set_xticks(x, labels)
    ax.set_ylabel("오차 (mL)")
    ax.set_title("주요 회귀 모델 비교", fontweight="bold")
    ax.set_ylim(0, max(np.nanmax(rmse), np.nanmax(mae)) * 1.25)
    for xi, m in zip(x, mae):
        ax.text(xi - width / 2, m + max(rmse) * 0.04, f"{m:.2f}", ha="center", fontsize=19, fontweight="bold")
    for xi, r in zip(x, rmse):
        ax.text(xi + width / 2, r + max(rmse) * 0.04, f"{r:.2f}", ha="center", fontsize=19, fontweight="bold")
    ax.legend(frameon=False, loc="upper left")
    style_ax(ax)
    path = OUT_DIR / "05b_model_algorithm_comparison_zoom.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_run_error_bars(predictions: dict[str, dict[str, float | str]], runs: list[RunData]) -> Path:
    fig, ax = plt.subplots(figsize=(18, 10), constrained_layout=True)
    labels = []
    errors = []
    colors = []
    for run in runs:
        pred = predictions.get(run.basename, {})
        err = float(pred.get("signed_error", math.nan))
        if not math.isfinite(err):
            continue
        labels.append(f"{run.type_label}\n{run.concentration:g}M")
        errors.append(err)
        colors.append(COLORS["good"] if abs(err) <= 1 else COLORS["warn"] if abs(err) <= 3 else COLORS["bad"])
    x = np.arange(len(labels))
    bars = ax.bar(x, errors, color=colors, width=0.72)
    ax.axhline(0, color=COLORS["actual"], linewidth=2.5)
    ax.set_xticks(x, labels, rotation=0)
    ax.set_ylabel("예측 오차 (mL)")
    ax.set_title("12개 실험 run별 예측 오차", fontweight="bold")
    ymax = max(abs(v) for v in errors) * 1.25
    ax.set_ylim(-ymax, ymax)
    for bar, e in zip(bars, errors):
        ax.text(bar.get_x() + bar.get_width() / 2, e + (0.25 if e >= 0 else -0.55), f"{e:+.2f}", ha="center", va="bottom" if e >= 0 else "top", fontsize=16, fontweight="bold")
    style_ax(ax)
    path = OUT_DIR / "06_run_signed_error_bars.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_dataset_summary(runs: list[RunData]) -> Path:
    fig, axes = plt.subplots(1, 3, figsize=(20, 8), constrained_layout=True)
    fig.suptitle("수집 데이터 구성 요약", fontweight="bold")
    # Runs by type.
    counts = [sum(1 for r in runs if r.titration_type == t) for t in TYPE_ORDER]
    labels = [TYPE_LABELS[t] for t in TYPE_ORDER]
    axes[0].bar(labels, counts, color=["#2563EB", "#7C3AED", "#059669", "#EA580C"])
    axes[0].set_title("적정 종류별 run 수", fontweight="bold")
    axes[0].set_ylim(0, max(counts) + 1)
    for i, c in enumerate(counts):
        axes[0].text(i, c + 0.1, str(c), ha="center", fontweight="bold", fontsize=24)
    # Row counts.
    total_rows = sum(r.row_count for r in runs)
    axes[1].bar(["총 CSV 행", "실험 run"], [total_rows, len(runs)], color=["#0EA5E9", "#111827"])
    axes[1].set_title("전체 데이터량", fontweight="bold")
    for i, v in enumerate([total_rows, len(runs)]):
        axes[1].text(i, v + max(total_rows, len(runs)) * 0.04, f"{v:,}", ha="center", fontweight="bold", fontsize=24)
    # Concentration distribution.
    concs = sorted(set(r.concentration for r in runs))
    conc_counts = [sum(1 for r in runs if abs(r.concentration - c) < 1e-9) for c in concs]
    axes[2].bar([f"{c:g}M" for c in concs], conc_counts, color="#10B981")
    axes[2].set_title("농도 조건별 run 수", fontweight="bold")
    axes[2].set_ylim(0, max(conc_counts) + 1)
    for i, c in enumerate(conc_counts):
        axes[2].text(i, c + 0.1, str(c), ha="center", fontweight="bold", fontsize=24)
    for ax in axes:
        style_ax(ax)
    path = OUT_DIR / "07_dataset_summary.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_individual_runs(runs: list[RunData], predictions: dict[str, dict[str, float | str]]) -> list[Path]:
    paths: list[Path] = []
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    for run in runs:
        fig, ax1 = plt.subplots(figsize=(14, 9), constrained_layout=True)
        ax1.set_title(f"{run.short_label} 수집 신호", fontweight="bold")
        hx, hy = binned_series(run.x_ml, run.hue_norm, bin_width=0.65)
        sx, sy = binned_series(run.x_ml, run.sat_norm, bin_width=0.65)
        tx, ty = binned_series(run.x_ml, run.thermal_norm, bin_width=0.65)
        ax1.plot(hx, hy, color=COLORS["color"], linewidth=4, label="H 색상")
        ax1.plot(sx, sy, color="#7C3AED", linewidth=3.2, label="S 채도")
        ax1.plot(tx, ty, color=COLORS["thermal"], linewidth=4, label="온도 변화")
        ax1.axvline(run.equivalence_ml, color=COLORS["actual"], linewidth=3, linestyle="--", label="이론 당량점")
        pred = predictions.get(run.basename, {})
        ax1.set_xlabel("주입량 (mL)")
        ax1.set_ylabel("정규화 신호")
        ax1.set_ylim(-0.05, 1.08)
        ax1.set_xlim(0, max(run.max_volume_ml, run.equivalence_ml) * 1.05)
        style_ax(ax1)
        ax1.legend(loc="upper left", frameon=True, facecolor="white", edgecolor="#E5E7EB")
        note = f"이론 당량점 {run.equivalence_ml:.1f} mL"
        ax1.text(0.98, 0.05, note, transform=ax1.transAxes, ha="right", va="bottom", fontsize=20, fontweight="bold", bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="#E5E7EB"))
        path = RUN_DIR / f"{safe_file_label(run.basename)}_{run.titration_type}_{run.concentration:g}M.png"
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        paths.append(path)
    return paths


def write_readme(paths: list[Path], run_paths: list[Path]) -> Path:
    readme = OUT_DIR / "README.txt"
    lines = [
        "포스터용 시각화 파일 목록",
        "",
        "공통 스타일: Pretendard 폰트, 큰 제목/축 글자, 흰 배경, PNG 출력",
        "",
        "주요 그림",
    ]
    descriptions = {
        "01_all_runs_sensor_curves_grid.png": "12개 실험 run 전체의 색 차이량과 열화상 변화. 수집 데이터만 표시하고 모델 예측값은 제외.",
        "01b_all_runs_hsv_channels_grid.png": "실제 HSV 성분 변화. S/V까지 확인할 때 사용하는 보조 그림. 모델 예측값은 제외.",
        "01c_all_runs_hue_thermal_grid.png": "H 색상과 온도 변화만 남긴 포스터 권장 그림. 수집 데이터와 이론 당량점만 표시.",
        "02_type_mean_sensor_curves.png": "적정 종류별 평균 H 색상과 온도 변화. 당량점 전후의 평균 경향 비교.",
        "03_prediction_actual_vs_predicted.png": "이론 당량점과 머신러닝 예측 당량점 산점도.",
        "04_typewise_mae_bar.png": "적정 종류별 MAE 비교. 강산-강염기 성능이 가장 안정적임을 보여줌.",
        "05_model_algorithm_comparison.png": "Ridge, KNN, Random Forest, Extra Trees 모델 비교. 최종 모델 선정 근거.",
        "05b_model_algorithm_comparison_zoom.png": "Ridge를 제외하고 주요 모델만 확대 비교. 포스터에는 이 그림이 더 읽기 쉬움.",
        "06_run_signed_error_bars.png": "12개 run별 예측 오차. 어느 조건에서 크게 틀렸는지 확인.",
        "07_dataset_summary.png": "데이터 구성 요약. 4종류, 3농도, 총 12개 run 구조 설명.",
    }
    for path in paths:
        lines.append(f"{path.name}\t{descriptions.get(path.name, '')}")
    lines.extend(["", "개별 run 그림", "run_curves 폴더 안에 각 실험별 평활 색 변화/온도 변화 그래프 12개 저장."])
    for path in run_paths:
        lines.append(path.name)
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return readme


def main() -> int:
    setup_font()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    runs = load_runs()
    predictions = load_predictions()
    main_paths = [
        plot_all_runs_grid(runs, predictions),
        plot_all_runs_hue_thermal_grid(runs, predictions),
        plot_all_runs_hsv_channels_grid(runs, predictions),
        plot_type_mean_curves(runs),
        plot_prediction_scatter(predictions, runs),
        plot_typewise_mae(),
        plot_algorithm_comparison(),
        plot_algorithm_comparison_zoom(),
        plot_run_error_bars(predictions, runs),
        plot_dataset_summary(runs),
    ]
    run_paths = plot_individual_runs(runs, predictions)
    readme = write_readme(main_paths, run_paths)
    print("Generated poster visuals:")
    for path in main_paths:
        print(path)
    print(readme)
    print(f"Individual run curves: {len(run_paths)} files in {RUN_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
