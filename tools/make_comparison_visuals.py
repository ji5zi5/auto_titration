#!/usr/bin/env python3
"""Build reproducible comparison figures from the repository's frozen evidence.

Only the Python standard library and matplotlib are used.  The script deliberately
keeps the initial common-pipeline algorithm benchmark, older baseline/modality
evaluations, and the current final evaluator in separately labelled scopes.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, PowerNorm
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs/report_evidence_no_new_wet/comparison_visuals"
SOURCE = OUT / "source_data"

INK = "#172B4D"
GRID = "#D9E2EC"
WHITE = "#FFFFFF"
OKABE = {
    "orange": "#E69F00",
    "sky": "#56B4E9",
    "green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "vermillion": "#D55E00",
    "purple": "#CC79A7",
    "black": "#000000",
}
TYPE_ORDER = [
    "strong_acid_strong_base",
    "strong_acid_weak_base",
    "weak_acid_strong_base",
    "weak_acid_weak_base",
]
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
TYPE_COLOR = dict(zip(TYPE_ORDER, [OKABE["blue"], OKABE["orange"], OKABE["green"], OKABE["purple"]]))

METHOD_ORDER = [
    "manual_current",
    "color_major_slope",
    "color_thermal_adaptive_threshold",
    "machine_learning_color",
    "machine_learning_thermal",
    "machine_learning_fusion",
    "current_final_model",
]
METHOD_LABEL = {
    "manual_current": "수동 적정 (현재 기록)",
    "color_major_slope": "색상 기울기 (비ML)",
    "color_thermal_adaptive_threshold": "색상+열 임계값 (비ML)",
    "machine_learning_color": "색상 ML (이전 파이프라인)",
    "machine_learning_thermal": "열 ML (이전 파이프라인)",
    "machine_learning_fusion": "융합 ML (이전 파이프라인)",
    "current_final_model": "최종 선택 모델 (현재)",
}
METHOD_COLOR = {
    "manual_current": OKABE["black"],
    "color_major_slope": OKABE["sky"],
    "color_thermal_adaptive_threshold": OKABE["yellow"],
    "machine_learning_color": OKABE["orange"],
    "machine_learning_thermal": OKABE["purple"],
    "machine_learning_fusion": OKABE["vermillion"],
    "current_final_model": OKABE["green"],
}


def read_csv(path: str) -> list[dict[str, str]]:
    with (REPO / path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_json(path: str) -> dict:
    return json.loads((REPO / path).read_text(encoding="utf-8"))


def write_csv(name: str, rows: list[dict], fields: list[str] | None = None) -> None:
    path = SOURCE / name
    if not rows:
        raise ValueError(f"No source rows for {name}")
    fields = fields or list(rows[0])
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def style() -> None:
    matplotlib.rcParams.update({
        "font.family": "Pretendard",
        "font.size": 12,
        "axes.titlesize": 18,
        "axes.titleweight": "bold",
        "axes.labelsize": 13,
        "axes.labelcolor": INK,
        "axes.edgecolor": GRID,
        "axes.linewidth": 0.8,
        "xtick.color": INK,
        "ytick.color": INK,
        "text.color": INK,
        "figure.facecolor": WHITE,
        "axes.facecolor": WHITE,
        "savefig.facecolor": WHITE,
        "savefig.dpi": 300,
    })


def finish(fig: plt.Figure, name: str) -> None:
    fig.savefig(OUT / name, dpi=300, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)


def clean_axis(ax, grid_axis: str = "x") -> None:
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def annotate_bars(ax, bars, fmt: str = "{:.2f}", pad: float = 4) -> None:
    for bar in bars:
        value = bar.get_width()
        ax.annotate(fmt.format(value), (value, bar.get_y() + bar.get_height() / 2),
                    xytext=(pad, 0), textcoords="offset points", va="center", fontsize=10)


def metrics(rows: list[dict], actual: str, predicted: str) -> dict[str, float]:
    errors = [float(row[predicted]) - float(row[actual]) for row in rows]
    apes = [abs(err) / float(row[actual]) * 100 for err, row in zip(errors, rows)]
    n = len(rows)
    return {
        "run_count": n,
        "mae_ml": sum(abs(err) for err in errors) / n,
        "rmse_ml": math.sqrt(sum(err * err for err in errors) / n),
        "mape_percent": sum(apes) / n,
        "within_1pct_rate": sum(v <= 1 for v in apes) / n,
        "within_2pct_rate": sum(v <= 2 for v in apes) / n,
        "within_5pct_rate": sum(v <= 5 for v in apes) / n,
    }


def condition_key(titration_type: str, volume: float) -> tuple[str, int]:
    return titration_type, int(round(volume))


def load_evidence():
    summary = read_json("data/ml/type_conditioned_sensor_sequence_search/summary.json")
    condition_final = read_csv("docs/report_evidence_no_new_wet/figures/source_data/01_02_condition_predictions.csv")
    nonml_runs = read_csv("data/analysis/non_ml_baseline_comparison/per_run_predictions.csv")
    modality_overall = read_csv("data/ml/report_modality_sensor_features_only/overall_comparison.csv")
    manual_raw = read_csv("data/report/manual_titration_results.csv")
    algorithm = read_csv("data/ml/curve_equivalence_current/model_algorithm_comparison.csv")
    repeat = read_json("data/analysis/july_unknown_repeatability/july_unknown_repeatability_summary.json")

    ko_to_type = {value: key for key, value in TYPE_KO.items()}
    manual = []
    for row in manual_raw:
        actual = float(row["reference_equivalence_ml"])
        predicted = float(row["manual_endpoint_ml"])
        titration_type = ko_to_type[row["titration_type"]]
        manual.append({
            "method": "manual_current", "titration_type": titration_type,
            "actual_equivalence_volume_ml": actual, "predicted_equivalence_volume_ml": predicted,
            "signed_error_ml": predicted - actual,
            "signed_error_percent": (predicted - actual) / actual * 100,
            "ape_percent": abs(predicted - actual) / actual * 100,
        })

    final = []
    for row in condition_final:
        actual = float(row["actual_equivalence_volume_ml"])
        predicted = float(row["predicted_equivalence_volume_ml"])
        final.append({
            "method": "current_final_model", "titration_type": row["titration_type"],
            "actual_equivalence_volume_ml": actual, "predicted_equivalence_volume_ml": predicted,
            "signed_error_ml": predicted - actual,
            "signed_error_percent": (predicted - actual) / actual * 100,
            "ape_percent": abs(predicted - actual) / actual * 100,
            "run_path": row["run_path"],
        })
    return summary, condition_final, nonml_runs, modality_overall, manual, algorithm, repeat, final


def figure_00() -> None:
    """Plot the four June 0.15 M sensor traces without using legacy paths."""
    selected: dict[str, tuple[Path, list[dict[str, str]]]] = {}
    for path in sorted((REPO / "머신러닝용 파일모음").glob("*.csv")):
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        if not rows or rows[0].get("sample_concentration_M") != "0.15":
            continue
        titration_type = rows[0]["titration_type"]
        if titration_type in TYPE_ORDER:
            selected[titration_type] = (path, rows)
    if set(selected) != set(TYPE_ORDER):
        raise ValueError(f"Expected one 0.15 M June run per type, found {sorted(selected)}")

    source_rows = []
    traces = {}
    for titration_type in TYPE_ORDER:
        path, raw_rows = selected[titration_type]
        trace = []
        for row in raw_rows:
            try:
                volume = float(row["injected_volume_ml"])
                hue = float(row["visible_H_mean"])
            except (KeyError, TypeError, ValueError):
                continue
            thermal_kind = "thermal_roi_avg_celsius"
            thermal_unit = "°C"
            thermal_text = row.get("thermal_roi_avg", "")
            if thermal_text == "":
                thermal_kind = "thermal_raw_roi_p50"
                thermal_unit = "raw"
                thermal_text = row.get("thermal_raw_roi_p50", "")
            try:
                thermal = float(thermal_text)
            except (TypeError, ValueError):
                continue
            item = {
                "source_file": path.name,
                "titration_type": titration_type,
                "titration_type_ko": TYPE_KO[titration_type],
                "sample_concentration_M": 0.15,
                "injected_volume_ml": volume,
                "visible_H_mean": hue,
                "thermal_signal": thermal,
                "thermal_signal_kind": thermal_kind,
                "thermal_unit": thermal_unit,
            }
            source_rows.append(item)
            trace.append(item)
        traces[titration_type] = trace
    write_csv("00_representative_sensor_curves_by_type.csv", source_rows)

    fig, axes = plt.subplots(2, 2, figsize=(10, 6), sharex=True)
    for ax, titration_type in zip(axes.flat, TYPE_ORDER):
        trace = traces[titration_type]
        x = [r["injected_volume_ml"] for r in trace]
        hue = [r["visible_H_mean"] for r in trace]
        thermal = [r["thermal_signal"] for r in trace]
        color_line = ax.plot(x, hue, color=TYPE_COLOR[titration_type], linewidth=1.8, label="색상 H 평균")[0]
        thermal_ax = ax.twinx()
        thermal_line = thermal_ax.plot(x, thermal, color=OKABE["vermillion"], linewidth=1.4,
                                       linestyle="--", alpha=.9, label="열화상 ROI 평균")[0]
        ax.axvline(30, color=INK, linewidth=1, linestyle=":")
        ax.set_title(TYPE_KO[titration_type], color=TYPE_COLOR[titration_type], fontsize=14)
        ax.set_ylabel("색상 H 평균")
        thermal_ax.set_ylabel("ROI 온도 (°C)", color=OKABE["vermillion"])
        thermal_ax.tick_params(axis="y", colors=OKABE["vermillion"])
        ax.grid(axis="both", color=GRID, linewidth=.7); ax.set_axisbelow(True)
        ax.legend([color_line, thermal_line], ["색상 H 평균", "열화상 ROI 평균"], frameon=False,
                  loc="best", fontsize=9)
    for ax in axes[-1]:
        ax.set_xlabel("주입 부피 (mL)")
    fig.tight_layout()
    finish(fig, "00_representative_sensor_curves_by_type.png")


def long_per_run(nonml_runs, manual, final) -> list[dict]:
    rows = []
    for row in nonml_runs:
        method = row["method"]
        if method not in METHOD_ORDER:
            continue
        actual = float(row["actual_equivalence_volume_ml"])
        predicted = float(row["predicted_equivalence_volume_ml"])
        rows.append({"method": method, "titration_type": row["titration_type"],
                     "actual_equivalence_volume_ml": actual, "predicted_equivalence_volume_ml": predicted,
                     "signed_error_ml": predicted - actual, "signed_error_percent": (predicted-actual)/actual*100,
                     "ape_percent": abs(predicted-actual)/actual*100})
    rows.extend(manual)
    rows.extend(final)
    return rows


def figure_01(algorithm):
    rows = [r for r in algorithm if r["scope"] == "overall"]
    source = [{"pipeline_scope": "initial_common_pipeline", "algorithm": r["model"],
               "mape_percent": float(r["mae_percent_of_equivalence"]), "run_count": int(r["run_count"])} for r in rows]
    write_csv("01_initial_common_algorithm_mape.csv", source)
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = ["Ridge", "KNN", "Random Forest", "Extra Trees"]
    values = [r["mape_percent"] for r in source]
    bars = ax.barh(labels[::-1], values[::-1], color=[OKABE["blue"], OKABE["orange"], OKABE["green"], OKABE["purple"]][::-1])
    annotate_bars(ax, bars, "{:.1f}%")
    ax.set_xlabel("MAPE (%) · 동일한 초기 파이프라인")
    clean_axis(ax)
    finish(fig, "01_initial_common_algorithm_mape.png")


def figure_02(summary):
    metric_by_type = {r["titration_type"]: r for r in summary["stratified_metrics"] if r["seed"] == 42}
    family_label = {"pls": "PLS", "kernel_ridge_rbf": "RBF KRR", "lda": "LDA", "qda": "QDA"}
    source = []
    for t in TYPE_ORDER:
        source.append({"titration_type": t, "titration_type_ko": TYPE_KO[t],
                       "selected_evaluator": family_label[summary["type_configs"][t]["family"]],
                       "mape_percent": metric_by_type[t]["mape_percent"], "run_count": 3,
                       "evaluation_scope": "current_final_same_12_run_development_selection"})
    write_csv("02_selected_evaluator_by_type.csv", source)
    fig, ax = plt.subplots(figsize=(8, 5))
    y = list(range(4))
    bars = ax.barh(y[::-1], [r["mape_percent"] for r in source][::-1], color=[TYPE_COLOR[t] for t in TYPE_ORDER][::-1])
    ax.set_yticks(y[::-1], [f'{r["titration_type_ko"]} · {r["selected_evaluator"]}' for r in source][::-1])
    annotate_bars(ax, bars, "{:.3f}%")
    ax.set_xlabel("MAPE (%)")
    clean_axis(ax)
    finish(fig, "02_selected_evaluator_by_type.png")


def figure_03(summary):
    families = ["PLS", "LDA", "QDA", "Prototype", "Pairwise Ridge", "RBF KRR", "Polynomial KRR", "RBF SVR"]
    selected_map = {"PLS": "강산-강염기", "RBF KRR": "강산-약염기", "LDA": "약산-강염기", "QDA": "약산-약염기"}
    source = [{"explored_family": f, "selected": "yes" if f in selected_map else "no",
               "selected_for_titration_type": selected_map.get(f, "") } for f in families]
    write_csv("03_advanced_family_selection_map.csv", source)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.set_xlim(0, 12); ax.set_ylim(0, 10); ax.axis("off")
    candidate_group = FancyBboxPatch(
        (0.15, 0.55), 4.55, 8.7, boxstyle="round,pad=0.12",
        facecolor="#FAFCFD", edgecolor=GRID, linewidth=1.2,
    )
    ax.add_patch(candidate_group)
    ax.text(2.43, 8.85, "후보 평가기 8계열", ha="center", va="center", weight="bold", color=INK)
    for i, family in enumerate(families):
        x = 0.4 + (i % 2) * 2.05; y = 7.65 - (i // 2) * 1.75
        box = FancyBboxPatch((x, y), 1.8, 0.85, boxstyle="round,pad=0.08", facecolor="#F5F8FA",
                             edgecolor=GRID, linewidth=1.2)
        ax.add_patch(box); ax.text(x + .9, y + .425, family, ha="center", va="center", fontsize=10)

    selection_box = FancyBboxPatch(
        (5.05, 4.05), 1.9, 1.25, boxstyle="round,pad=0.10",
        facecolor=WHITE, edgecolor=INK, linewidth=1.4,
    )
    ax.add_patch(selection_box)
    ax.text(6.0, 4.675, "적정 종류별\n교차검증 선택", ha="center", va="center", fontsize=10.5, weight="bold")
    ax.add_patch(FancyArrowPatch((4.72, 4.675), (5.0, 4.675), arrowstyle="-|>", mutation_scale=16,
                                 color=INK, linewidth=1.4))
    selected = [("PLS", TYPE_ORDER[0]), ("RBF KRR", TYPE_ORDER[1]), ("LDA", TYPE_ORDER[2]), ("QDA", TYPE_ORDER[3])]
    for i, (family, t) in enumerate(selected):
        y = 7.65 - i * 1.75
        box = FancyBboxPatch((7.65, y), 3.9, 0.85, boxstyle="round,pad=0.08", facecolor=TYPE_COLOR[t],
                             edgecolor="none", alpha=.9)
        ax.add_patch(box); ax.text(9.6, y + .425, f"{TYPE_KO[t]}  ·  {family}", ha="center", va="center",
                                   color=WHITE, weight="bold", fontsize=11)
        ax.add_patch(FancyArrowPatch((6.95, 4.675), (7.58, y + .425), arrowstyle="-|>", mutation_scale=14,
                                     color=TYPE_COLOR[t], linewidth=1.2, connectionstyle="arc3,rad=0.08"))
    finish(fig, "03_advanced_family_selection_map.png")


def heatmap_figure(number, title, source_rows, row_labels, col_labels, matrix, filename, source_name):
    flat = []
    for i, method in enumerate(row_labels):
        for j, col in enumerate(col_labels):
            flat.append({"method": method, "method_label": METHOD_LABEL[method], "column": col,
                         "mape_or_ape_percent": matrix[i][j]})
    write_csv(source_name, flat)
    cmap = LinearSegmentedColormap.from_list("error", [WHITE, OKABE["yellow"], OKABE["orange"], OKABE["vermillion"]])
    fig, ax = plt.subplots(figsize=(10, 6))
    maximum = max(max(r) for r in matrix)
    norm = PowerNorm(gamma=0.45, vmin=0, vmax=maximum)
    im = ax.imshow(matrix, cmap=cmap, aspect="auto", norm=norm)
    ax.set_xticks(range(len(col_labels)), col_labels, rotation=35, ha="right")
    ax.set_yticks(range(len(row_labels)), [METHOD_LABEL[m] for m in row_labels])
    for i, row in enumerate(matrix):
        for j, value in enumerate(row):
            ax.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=8,
                    color=WHITE if norm(value) > .64 else INK)
    cbar = fig.colorbar(im, ax=ax, pad=.02); cbar.set_label("오차 (%) · 저오차 구간 확대 색상")
    fig.tight_layout()
    finish(fig, filename)


def figures_04_05(per_run):
    lookup = {(r["method"],) + condition_key(r["titration_type"], r["actual_equivalence_volume_ml"]): r["ape_percent"] for r in per_run}
    conditions = [(t, volume) for t in TYPE_ORDER for volume in (20, 30, 40)]
    labels = [f"{TYPE_SHORT[t]} {v}" for t, v in conditions]
    matrix = [[lookup[(m, t, v)] for t, v in conditions] for m in METHOD_ORDER]
    heatmap_figure(4, "조건별 절대백분율오차: 이전 파이프라인과 현재 최종 모델 구분",
                   [], METHOD_ORDER, labels, matrix, "04_condition_method_ape_heatmap.png", "04_condition_method_ape_heatmap.csv")
    type_matrix = []
    for m in METHOD_ORDER:
        type_matrix.append([sum(lookup[(m, t, v)] for v in (20, 30, 40)) / 3 for t in TYPE_ORDER])
    heatmap_figure(5, "적정 종류별 MAPE 비교", [], METHOD_ORDER, [TYPE_KO[t] for t in TYPE_ORDER], type_matrix,
                   "05_type_method_mape_heatmap.png", "05_type_method_mape_heatmap.csv")


def aggregate_method_metrics(per_run):
    grouped = defaultdict(list)
    for row in per_run: grouped[row["method"]].append(row)
    result = {}
    for method in METHOD_ORDER:
        result[method] = metrics(grouped[method], "actual_equivalence_volume_ml", "predicted_equivalence_volume_ml")
    return result


def figure_06(aggregates):
    rows = [{"method": m, "method_label": METHOD_LABEL[m], **aggregates[m]} for m in METHOD_ORDER]
    write_csv("06_comprehensive_method_mape.csv", rows)
    ordered = sorted(rows, key=lambda r: r["mape_percent"], reverse=True)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    bars = ax.barh([r["method_label"] for r in ordered], [r["mape_percent"] for r in ordered],
                   color=[METHOD_COLOR[r["method"]] for r in ordered])
    annotate_bars(ax, bars, "{:.3f}%")
    ax.set_xlabel("MAPE (%) · 각 방법 12개 조건")
    clean_axis(ax)
    finish(fig, "06_comprehensive_method_mape.png")


def figure_07(aggregates):
    rows = [{"method": m, "method_label": METHOD_LABEL[m], "mae_ml": aggregates[m]["mae_ml"],
             "rmse_ml": aggregates[m]["rmse_ml"], "run_count": 12} for m in METHOD_ORDER]
    write_csv("07_comprehensive_method_mae_rmse.csv", rows)
    fig, axes = plt.subplots(1, 2, figsize=(10, 5.5), sharey=True)
    labels = [r["method_label"] for r in rows][::-1]
    for ax, metric_name, title in zip(axes, ("mae_ml", "rmse_ml"), ("MAE", "RMSE")):
        values = [r[metric_name] for r in rows][::-1]
        bars = ax.barh(labels, values, color=[METHOD_COLOR[r["method"]] for r in rows][::-1])
        annotate_bars(ax, bars, "{:.2f}")
        ax.set_title(title); ax.set_xlabel("mL"); clean_axis(ax)
    fig.tight_layout()
    finish(fig, "07_comprehensive_method_mae_rmse.png")


def figure_08(aggregates):
    rows = []
    for m in METHOD_ORDER:
        rows.append({"method": m, "method_label": METHOD_LABEL[m],
                     "within_1pct_percent": aggregates[m]["within_1pct_rate"] * 100,
                     "within_2pct_percent": aggregates[m]["within_2pct_rate"] * 100,
                     "within_5pct_percent": aggregates[m]["within_5pct_rate"] * 100,
                     "recomputed_from_per_run": "yes"})
    write_csv("08_tolerance_attainment.csv", rows)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    y = list(range(len(rows))); h = .22
    for offset, field, color, label in [(-h, "within_1pct_percent", OKABE["blue"], "±1%"),
                                        (0, "within_2pct_percent", OKABE["orange"], "±2%"),
                                        (h, "within_5pct_percent", OKABE["green"], "±5%")]:
        ax.barh([v + offset for v in y], [r[field] for r in rows], height=h, color=color, label=label)
    ax.set_yticks(y, [r["method_label"] for r in rows]); ax.set_xlim(0, 108)
    ax.set_xlabel("허용오차 이내 조건 비율 (%)")
    ax.legend(ncol=3, frameon=False, loc="lower right"); clean_axis(ax)
    finish(fig, "08_tolerance_attainment.png")


def grouped_condition_figure(number, title, methods, per_run, filename, source_name, dot=False):
    lookup = {(r["method"],) + condition_key(r["titration_type"], r["actual_equivalence_volume_ml"]): r for r in per_run}
    conditions = [(t, v) for t in TYPE_ORDER for v in (20, 30, 40)]
    source = []
    for t, v in conditions:
        for m in methods:
            source.append({"condition": f"{TYPE_SHORT[t]} {v}", "titration_type": t, "volume_ml": v,
                           "method": m, "method_label": METHOD_LABEL[m], "ape_percent": lookup[(m, t, v)]["ape_percent"]})
    write_csv(source_name, source)
    fig, ax = plt.subplots(figsize=(9, 6))
    y = list(range(len(conditions))); offsets = [-.18, .18]
    for idx, m in enumerate(methods):
        values = [lookup[(m, t, v)]["ape_percent"] for t, v in conditions]
        if dot:
            ax.scatter(values, [p + offsets[idx] for p in y], s=55, color=METHOD_COLOR[m], label=METHOD_LABEL[m], zorder=3)
        else:
            ax.barh([p + offsets[idx] for p in y], values, height=.32, color=METHOD_COLOR[m], label=METHOD_LABEL[m])
    ax.set_yticks(y, [f"{TYPE_SHORT[t]} {v}" for t, v in conditions]); ax.invert_yaxis()
    ax.set_xlabel("APE (%)"); ax.legend(frameon=False, loc="lower right")
    clean_axis(ax)
    finish(fig, filename)


def signed_error_figure(rows, method, title, filename, source_name):
    ordered = sorted([r for r in rows if r["method"] == method], key=lambda r: (TYPE_ORDER.index(r["titration_type"]), r["actual_equivalence_volume_ml"]))
    source = [{"condition": f'{TYPE_SHORT[r["titration_type"]]} {int(r["actual_equivalence_volume_ml"])}',
               "titration_type": r["titration_type"], "actual_equivalence_volume_ml": r["actual_equivalence_volume_ml"],
               "predicted_equivalence_volume_ml": r["predicted_equivalence_volume_ml"],
               "signed_error_ml": r["signed_error_ml"], "signed_error_percent": r["signed_error_percent"]} for r in ordered]
    write_csv(source_name, source)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    colors = [TYPE_COLOR[r["titration_type"]] for r in ordered]
    ax.bar(range(len(source)), [r["signed_error_percent"] for r in source], color=colors)
    ax.axhline(0, color=INK, linewidth=1)
    ax.set_xticks(range(len(source)), [r["condition"] for r in source], rotation=35, ha="right")
    ax.set_ylabel("부호 있는 오차 (%)"); clean_axis(ax, "y")
    fig.tight_layout(); finish(fig, filename)


def figure_12_13(repeat):
    rows = [{"repeat_index": r["repeat_index"], "source_file": r["source_file"],
             "frozen_model_concentration_M": r["frozen_model_predicted_concentration_M"],
             "recorded_old_model_concentration_M": r["recorded_old_model_prediction_M"],
             "actual_concentration": "unknown_not_standardized"} for r in repeat["rows"]]
    write_csv("12_unknown_repeatability_concentration.csv", rows)
    fig, ax = plt.subplots(figsize=(8, 5))
    x = [r["repeat_index"] for r in rows]; y = [r["frozen_model_concentration_M"] for r in rows]
    bars = ax.bar(x, y, width=.55, color=OKABE["green"])
    for bar, value in zip(bars, y):
        ax.text(bar.get_x() + bar.get_width() / 2, value + max(y) * .006, f"{value:.4f}",
                ha="center", va="bottom", fontsize=11, color=INK)
    mean_value = sum(y) / len(y)
    ax.axhline(mean_value, color=INK, linestyle="--", linewidth=1.2)
    ax.set_xticks(x, [f"반복 {i}" for i in x]); ax.set_ylabel("예측 농도 (M)")
    ax.set_ylim(0, max(y) * 1.12)
    clean_axis(ax, "y")
    finish(fig, "12_unknown_repeatability_concentration.png")

    cv_rows = [
        {"model_scope": "recorded_old_model", "label": "기존 기록 모델", "cv_percent": repeat["recorded_old_model_repeatability"]["cv_percent"], "n": 3},
        {"model_scope": "frozen_current_model", "label": "동결 현재 모델", "cv_percent": repeat["frozen_model_repeatability"]["cv_percent"], "n": 3},
    ]
    write_csv("13_repeatability_cv_comparison.csv", cv_rows)
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.barh([r["label"] for r in cv_rows], [r["cv_percent"] for r in cv_rows], color=[OKABE["orange"], OKABE["green"]])
    annotate_bars(ax, bars, "{:.2f}%")
    ax.set_xlabel("변동계수 CV (%) · 각 3회, 기술 통계")
    clean_axis(ax); finish(fig, "13_repeatability_cv_comparison.png")


def figure_15(summary):
    rows = []
    for r in summary["stratified_metrics"]:
        if r["seed"] == 42:
            rows.append({"titration_type": r["titration_type"], "titration_type_ko": TYPE_KO[r["titration_type"]],
                         "mae_ml": r["mae_ml"], "rmse_ml": r["rmse_ml"], "run_count": r["run_count"]})
    rows.sort(key=lambda r: TYPE_ORDER.index(r["titration_type"]))
    write_csv("15_final_typewise_mae_rmse.csv", rows)
    fig, ax = plt.subplots(figsize=(8, 5))
    x = list(range(4)); w=.34
    ax.bar([v-w/2 for v in x], [r["mae_ml"] for r in rows], width=w, color=OKABE["blue"], label="MAE")
    ax.bar([v+w/2 for v in x], [r["rmse_ml"] for r in rows], width=w, color=OKABE["orange"], label="RMSE")
    ax.set_xticks(x, [r["titration_type_ko"] for r in rows], rotation=15)
    ax.set_ylabel("오차 (mL)")
    ax.legend(frameon=False); clean_axis(ax, "y")
    finish(fig, "15_final_typewise_mae_rmse.png")


def figure_16(per_run):
    lookup = {(r["method"],) + condition_key(r["titration_type"], r["actual_equivalence_volume_ml"]): r["ape_percent"] for r in per_run}
    rows = []
    for volume in (20, 30, 40):
        for method in METHOD_ORDER:
            values = [lookup[(method, t, volume)] for t in TYPE_ORDER]
            rows.append({"volume_group_ml": volume, "method": method, "method_label": METHOD_LABEL[method],
                         "mape_percent": sum(values)/len(values), "condition_count": len(values)})
    write_csv("16_volume_group_mape.csv", rows)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    x = list(range(3)); width=.1
    for i, method in enumerate(METHOD_ORDER):
        values = [next(r["mape_percent"] for r in rows if r["method"] == method and r["volume_group_ml"] == v) for v in (20,30,40)]
        ax.bar([p + (i-3)*width for p in x], values, width=width, color=METHOD_COLOR[method], label=METHOD_LABEL[method])
    ax.set_xticks(x, ["20 mL", "30 mL", "40 mL"]); ax.set_ylabel("MAPE (%)")
    ax.legend(frameon=False, ncol=2, fontsize=9); clean_axis(ax, "y")
    finish(fig, "16_volume_group_mape.png")


def write_readme():
    text = """# Comparison visual suite

## Reproduction

Run `python3 tools/make_comparison_visuals.py` from the repository root. The generator uses only the Python standard library, matplotlib, CSV, and JSON; it does not use pandas. All PNG files are exported at 300 dpi with a white background and a width of at least 1800 pixels. Every figure has a matching CSV in `source_data/`.

## Provenance and caveats

- **00** — four June 0.15 M CSVs under `머신러닝용 파일모음/`, selected reproducibly by `sample_concentration_M=0.15` and one run per titration type. The plotted channels are `visible_H_mean` and calibrated `thermal_roi_avg` (with a raw ROI median fallback if calibrated ROI temperature is unavailable). The dotted vertical line marks the recorded theoretical 30 mL equivalence volume.
- **01** — `data/ml/curve_equivalence_current/model_algorithm_comparison.csv`, `scope=overall`. This is explicitly the **initial common pipeline**. Its Ridge/KNN/RF/ET scores must not be presented as head-to-head scores from the current final pipeline.
- **02–03, 15** — `data/ml/type_conditioned_sensor_sequence_search/summary.json`. Current final evaluator configuration and seed-42 stratified metrics. The three configured seeds produce identical predictions; seed 42 is used once to avoid triplication. The scope is same-12-run development/configuration selection, not independent external validation.
- **04–11, 14, 16** — current final condition values from `docs/report_evidence_no_new_wet/figures/source_data/01_02_condition_predictions.csv`; current manual values from `data/report/manual_titration_results.csv`; older non-ML and old-pipeline ML values from `data/analysis/non_ml_baseline_comparison/per_run_predictions.csv`. The labels preserve these different generations. Typewise, tolerance, and volume-group summaries are recomputed from the 12 condition rows.
- **06–08** — the three old modality ML series correspond to the same values published in `data/ml/report_modality_sensor_features_only/overall_comparison.csv`; values are recomputed from per-run data so tolerance and error metrics share one denominator. Current manual MAPE is exactly 2.00%; current final MAPE is 0.295% after rounding.
- **12–13** — `data/analysis/july_unknown_repeatability/july_unknown_repeatability_summary.json`. These are three participant-designated repeats of one unknown solution. The actual concentration was not independently standardized, so the figures support repeatability only, not accuracy.
- **03** — the eight explored advanced families are the search families used by the type-conditioned advanced ranker search; the four selected evaluators and their type routing are taken from the current summary. The diagram is deliberately nonnumeric.
- **16** — each 20/30/40 mL group contains one condition from each of four titration types (n=4). It is descriptive and small-sample; it is not a concentration generalization test.

## Placement recommendation

**Report body:** 00 (representative sensor curves; replacement for the legacy-path Fig. 8 asset), 02 (final evaluator by type), 06 (overall MAPE), 08 (tolerance attainment), 09 (manual vs final), 12 (frozen-model repeatability), and 15 (final typewise MAE/RMSE).

**Appendix / methods:** 01 (historical initial pipeline), 03 (search funnel), 04–05 (dense heatmaps), 07 (paired absolute metrics), 10–11 and 14 (condition diagnostics), 13 (old-vs-frozen repeatability CV), and 16 (small-n volume-group diagnostic).

Do not place 01 beside 02 in a way that implies a single shared pipeline. Do not interpret 12–13 as unknown-solution accuracy.
"""
    (OUT / "README.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True); SOURCE.mkdir(parents=True, exist_ok=True); style()
    summary, _, nonml_runs, _, manual, algorithm, repeat, final = load_evidence()
    per_run = long_per_run(nonml_runs, manual, final)
    figure_00(); figure_01(algorithm); figure_02(summary); figure_03(summary); figures_04_05(per_run)
    aggregates = aggregate_method_metrics(per_run)
    figure_06(aggregates); figure_07(aggregates); figure_08(aggregates)
    grouped_condition_figure(9, "수동 적정과 현재 최종 모델의 조건별 APE", ["manual_current", "current_final_model"], per_run,
                             "09_manual_vs_final_condition_ape.png", "09_manual_vs_final_condition_ape.csv")
    signed_error_figure(per_run, "manual_current", "수동 적정의 조건별 부호 있는 오차", "10_manual_signed_error.png", "10_manual_signed_error.csv")
    grouped_condition_figure(11, "비ML 기준선과 현재 최종 모델의 조건별 APE",
                             ["color_major_slope", "current_final_model"], per_run,
                             "11_nonml_vs_final_condition_ape.png", "11_nonml_vs_final_condition_ape.csv", dot=True)
    figure_12_13(repeat)
    signed_error_figure(per_run, "current_final_model", "현재 최종 모델의 조건별 부호 있는 오차",
                        "14_final_signed_error.png", "14_final_signed_error.csv")
    figure_15(summary); figure_16(per_run); write_readme()
    print(f"Generated 17 figures and 17 source CSVs in {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
