#!/usr/bin/env python3
"""Create Korean, print-ready figures for the type-conditioned ML result."""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager


ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = ROOT / "data/ml/type_conditioned_sensor_sequence_search"
SUMMARY_PATH = INPUT_DIR / "summary.json"
PREDICTIONS_PATH = INPUT_DIR / "outer_predictions.csv"
OUTPUT_DIR = ROOT / "docs/report_evidence_no_new_wet/figures"
SOURCE_DIR = OUTPUT_DIR / "source_data"

TYPE_ORDER = (
    "strong_acid_strong_base",
    "strong_acid_weak_base",
    "weak_acid_strong_base",
    "weak_acid_weak_base",
)
TYPE_LABELS = {
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

# Okabe-Ito palette: distinguishable for common forms of color-vision deficiency.
TYPE_COLORS = {
    "strong_acid_strong_base": "#0072B2",
    "strong_acid_weak_base": "#E69F00",
    "weak_acid_strong_base": "#009E73",
    "weak_acid_weak_base": "#CC79A7",
}
TYPE_MARKERS = {
    "strong_acid_strong_base": "o",
    "strong_acid_weak_base": "s",
    "weak_acid_strong_base": "^",
    "weak_acid_weak_base": "D",
}

INK = "#172B4D"
MUTED = "#667085"
GRID = "#D9E2EC"
ACCENT = "#0072B2"


def percent_label(value: float) -> str:
    rounded = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{rounded}%"


def setup_style() -> None:
    font_dir = Path.home() / ".local/share/fonts/Pretendard"
    for path in sorted(font_dir.glob("Pretendard-*.*tf")):
        font_manager.fontManager.addfont(str(path))
    plt.rcParams.update(
        {
            "font.family": "Pretendard",
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#98A2B3",
            "axes.labelcolor": INK,
            "axes.titlecolor": INK,
            "text.color": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "font.size": 13,
            "axes.titlesize": 20,
            "axes.labelsize": 15,
            "legend.fontsize": 11,
            "savefig.dpi": 300,
        }
    )


def load_summary() -> dict:
    if not SUMMARY_PATH.is_file():
        raise FileNotFoundError(
            f"필수 입력 summary.json이 없습니다: {SUMMARY_PATH}"
        )
    with SUMMARY_PATH.open(encoding="utf-8") as handle:
        summary = json.load(handle)
    if summary.get("schema_version") != "type_conditioned_sensor_union_development_v3":
        raise ValueError("현재 v3 평가 코드로 재생성한 summary.json이 필요합니다.")
    if summary.get("split", {}).get("independent_external_validation") is not False:
        raise ValueError("그림 입력의 개발/독립 검증 범위가 명시되지 않았습니다.")
    return summary


def read_predictions() -> list[dict[str, str]]:
    if not PREDICTIONS_PATH.is_file():
        raise FileNotFoundError(f"필수 입력 CSV가 없습니다: {PREDICTIONS_PATH}")
    with PREDICTIONS_PATH.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def representative_runs(summary: dict, rows: list[dict[str, str]]) -> list[dict]:
    seeds = summary.get("seeds")
    if not seeds:
        raise ValueError("summary.json에 seeds가 없습니다.")
    seed = str(seeds[0])
    chosen = [row for row in rows if row.get("seed") == seed]
    expected = int(summary.get("run_count", 0))
    if len(chosen) != expected or expected != 12:
        raise ValueError(f"대표 seed의 예측은 12개여야 합니다: seed={seed}, rows={len(chosen)}")

    by_seed: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)
    for row in rows:
        by_seed[row["seed"]][row["run_path"]] = (
            float(row["actual_equivalence_volume_ml"]),
            float(row["predicted_equivalence_volume_ml"]),
        )
    reference = by_seed[seed]
    if any(values != reference for values in by_seed.values()):
        raise ValueError("seed별 예측값이 서로 달라 대표 seed를 선택할 수 없습니다.")

    runs = []
    for row in chosen:
        titration_type = row["known_titration_type"]
        if titration_type not in TYPE_LABELS:
            raise ValueError(f"알 수 없는 적정종류: {titration_type}")
        actual = float(row["actual_equivalence_volume_ml"])
        predicted = float(row["predicted_equivalence_volume_ml"])
        ape = abs(predicted - actual) / actual * 100.0
        runs.append(
            {
                "seed": int(seed),
                "run_path": row["run_path"],
                "titration_type": titration_type,
                "titration_type_ko": TYPE_LABELS[titration_type],
                "condition_short": f"{TYPE_SHORT[titration_type]} {actual:.0f}",
                "actual_equivalence_volume_ml": actual,
                "predicted_equivalence_volume_ml": predicted,
                "absolute_error_ml": abs(predicted - actual),
                "ape_percent": ape,
            }
        )
    runs.sort(key=lambda x: (TYPE_ORDER.index(x["titration_type"]), x["actual_equivalence_volume_ml"]))

    summary_mape = float(summary["per_seed_metrics"][0]["mape_percent"])
    calculated_mape = sum(run["ape_percent"] for run in runs) / len(runs)
    if not math.isclose(calculated_mape, summary_mape, abs_tol=5e-6):
        raise ValueError(
            f"summary MAPE와 예측 CSV 계산값이 다릅니다: {summary_mape} vs {calculated_mape}"
        )
    return runs


def style_axis(ax, grid_axis: str = "y") -> None:
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.9, alpha=0.85)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def save_figure(fig, filename: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT_DIR / filename, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def write_csv(filename: str, rows: list[dict], fields: list[str]) -> None:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    with (SOURCE_DIR / filename).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def figure_actual_vs_predicted(runs: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(10.2, 7.0))
    low, high = 18.0, 42.0
    ax.plot([low, high], [low, high], color="#475467", linewidth=1.6, linestyle="--", label="일치선 (y=x)")
    offsets = ((-10, -31), (-40, 10), (10, -31), (10, 10))
    alignments = ("right", "right", "left", "left")
    for type_index, titration_type in enumerate(TYPE_ORDER):
        subset = [run for run in runs if run["titration_type"] == titration_type]
        ax.scatter(
            [run["actual_equivalence_volume_ml"] for run in subset],
            [run["predicted_equivalence_volume_ml"] for run in subset],
            s=125,
            marker=TYPE_MARKERS[titration_type],
            color=TYPE_COLORS[titration_type],
            edgecolor="white",
            linewidth=1.2,
            zorder=3,
            label=TYPE_LABELS[titration_type],
        )
        for run in subset:
            ax.annotate(
                f"{run['predicted_equivalence_volume_ml']:.2f}",
                (run["actual_equivalence_volume_ml"], run["predicted_equivalence_volume_ml"]),
                xytext=offsets[type_index],
                textcoords="offset points",
                fontsize=9.5,
                color=TYPE_COLORS[titration_type],
                ha=alignments[type_index],
                arrowprops={
                    "arrowstyle": "-",
                    "color": TYPE_COLORS[titration_type],
                    "linewidth": 0.7,
                    "alpha": 0.7,
                },
            )
    ax.set(xlim=(low, high), ylim=(low, high), xlabel="기준 당량점 (mL)", ylabel="모델 추정값 (mL)")
    ax.set_aspect("equal", adjustable="box")
    ax.set_title("기준 당량점과 모델 추정값", loc="left", fontweight="bold", pad=14)
    ax.legend(frameon=False, ncol=3, loc="upper left")
    style_axis(ax, "both")
    save_figure(fig, "01_actual_vs_predicted.png")


def figure_condition_ape(runs: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(12.0, 6.4))
    x = range(len(runs))
    values = [run["ape_percent"] for run in runs]
    bars = ax.bar(x, values, width=0.68, color=[TYPE_COLORS[run["titration_type"]] for run in runs])
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.055, percent_label(value), ha="center", va="bottom", fontsize=9.5)
    for level, color in ((1.0, "#D55E00"), (2.0, "#6B7280")):
        ax.axhline(level, color=color, linestyle="--", linewidth=1.4, label=f"{level:.0f}% 기준")
    ax.set_xticks(list(x), [run["condition_short"] for run in runs], rotation=0, ha="center")
    ax.set_ylabel("절대백분율오차 APE (%)")
    ax.set_xlabel("적정종류-기준 부피 (mL)")
    ax.set_ylim(0, 2.25)
    ax.set_title("12개 조건별 모델 추정 오차", loc="left", fontweight="bold", pad=14)
    ax.legend(frameon=False, ncol=2, loc="upper right")
    style_axis(ax)
    save_figure(fig, "02_ape_by_condition.png")


def typewise_rows(runs: list[dict]) -> list[dict]:
    result = []
    for titration_type in TYPE_ORDER:
        values = [run["ape_percent"] for run in runs if run["titration_type"] == titration_type]
        result.append(
            {
                "titration_type": titration_type,
                "titration_type_ko": TYPE_LABELS[titration_type],
                "run_count": len(values),
                "mape_percent": sum(values) / len(values),
            }
        )
    return result


def figure_typewise_mape(rows: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 6.2))
    bars = ax.bar(
        range(len(rows)),
        [row["mape_percent"] for row in rows],
        width=0.62,
        color=[TYPE_COLORS[row["titration_type"]] for row in rows],
    )
    for bar, row in zip(bars, rows):
        ax.text(bar.get_x() + bar.get_width() / 2, row["mape_percent"] + 0.018, percent_label(row["mape_percent"]), ha="center", fontweight="bold")
    ax.set_xticks(range(len(rows)), [row["titration_type_ko"] for row in rows], rotation=0, ha="center")
    ax.set_ylabel("MAPE (%)")
    ax.set_ylim(0, 0.58)
    ax.set_title("적정종류별 평균 절대백분율오차", loc="left", fontweight="bold", pad=14)
    style_axis(ax)
    save_figure(fig, "03_mape_by_titration_type.png")


def method_rows(summary: dict) -> list[dict]:
    new_mape = float(summary["per_seed_metrics"][0]["mape_percent"])
    return [
        {"method": "color_max_gradient", "method_ko": "색 최대기울기", "mape_percent": 4.67},
        {"method": "color_thermal_threshold", "method_ko": "색·온도 임계값", "mape_percent": 5.65},
        {"method": "legacy_ml_color", "method_ko": "기존 ML 색상", "mape_percent": 1.55},
        {"method": "legacy_ml_fusion", "method_ko": "기존 ML 융합", "mape_percent": 1.52},
        {"method": "type_conditioned_sensor_model", "method_ko": "새 조건부 모델", "mape_percent": new_mape},
    ]


def figure_method_mape(rows: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(10.4, 6.3))
    colors = ["#9CA3AF", "#6B7280", "#56B4E9", "#009E73", "#0072B2"]
    bars = ax.bar(range(len(rows)), [row["mape_percent"] for row in rows], width=0.64, color=colors)
    for bar, row in zip(bars, rows):
        ax.text(bar.get_x() + bar.get_width() / 2, row["mape_percent"] + 0.12, percent_label(row["mape_percent"]), ha="center", fontweight="bold")
    ax.set_xticks(range(len(rows)), [row["method_ko"] for row in rows], rotation=0, ha="center")
    ax.set_ylabel("MAPE (%)")
    ax.set_ylim(0, 6.45)
    ax.set_title("판정방식별 평균 절대백분율오차", loc="left", fontweight="bold", pad=14)
    style_axis(ax)
    save_figure(fig, "04_mape_by_method.png")


def main() -> None:
    summary = load_summary()
    runs = representative_runs(summary, read_predictions())
    type_rows = typewise_rows(runs)
    methods = method_rows(summary)

    setup_style()
    figure_actual_vs_predicted(runs)
    figure_condition_ape(runs)
    figure_typewise_mape(type_rows)
    figure_method_mape(methods)

    run_fields = list(runs[0])
    write_csv("01_02_condition_predictions.csv", runs, run_fields)
    write_csv("03_typewise_mape.csv", type_rows, list(type_rows[0]))
    write_csv("04_method_mape.csv", methods, list(methods[0]))
    print(f"생성 완료: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
