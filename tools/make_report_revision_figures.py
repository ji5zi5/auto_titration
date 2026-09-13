#!/usr/bin/env python3
"""Generate consistent, audit-friendly figures for the science-fair report revision.

Final report scope:
- current injected volume is excluded from ML features;
- color+thermal sensor-only fusion is the final smart-titration model;
- manual titration values are the 12 measured values supplied by the project team.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS = ROOT / "data/ml/report_modality_sensor_features_only/selected_predictions_color_thermal_fusion.csv"
OVERALL = ROOT / "data/ml/report_modality_sensor_features_only/overall_comparison.csv"
TYPEWISE = ROOT / "data/ml/report_modality_sensor_features_only/typewise_selection_color_thermal_fusion.csv"
MANUAL_RESULTS = ROOT / "data/report/manual_titration_results.csv"
OUT = ROOT / "docs/report_revision_figures"
SOURCE = OUT / "source_data"

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
TYPE_SHORT = {
    "strong_acid_strong_base": "강산-강염기",
    "strong_acid_weak_base": "강산-약염기",
    "weak_acid_strong_base": "약산-강염기",
    "weak_acid_weak_base": "약산-약염기",
}
TYPE_COLOR = {
    "strong_acid_strong_base": "#2563EB",
    "strong_acid_weak_base": "#7C3AED",
    "weak_acid_strong_base": "#EA580C",
    "weak_acid_weak_base": "#059669",
}
NAVY = "#172B4D"
BLUE = "#2563EB"
TEAL = "#059669"
ORANGE = "#EA580C"
RED = "#DC2626"
GRAY = "#64748B"
LIGHT = "#E2E8F0"
GRID = "#DCE3EC"

def setup_font() -> None:
    font_dir = Path.home() / ".local/share/fonts/Pretendard"
    for name in ["Pretendard-Regular.ttf", "Pretendard-SemiBold.ttf", "Pretendard-Bold.ttf"]:
        path = font_dir / name
        if path.exists():
            font_manager.fontManager.addfont(str(path))
    plt.rcParams.update({
        "font.family": "Pretendard",
        "axes.unicode_minus": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": NAVY,
        "axes.labelcolor": NAVY,
        "text.color": NAVY,
        "xtick.color": NAVY,
        "ytick.color": NAVY,
        "font.size": 13,
        "axes.titlesize": 18,
        "axes.labelsize": 14,
        "legend.fontsize": 11,
        "savefig.dpi": 240,
    })


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def manual_endpoints() -> dict[tuple[str, float], float]:
    type_key = {label: key for key, label in TYPE_LABEL.items()}
    endpoints: dict[tuple[str, float], float] = {}
    for row in read_csv(MANUAL_RESULTS):
        concentration = float(row["validation_concentration"].split()[0])
        endpoints[(type_key[row["titration_type"]], round(concentration, 2))] = float(
            row["manual_endpoint_ml"]
        )
    if len(endpoints) != 12:
        raise RuntimeError(f"expected 12 manual titration rows, found {len(endpoints)}")
    return endpoints


def ordered_runs() -> list[dict]:
    rows = read_csv(PREDICTIONS)
    endpoints = manual_endpoints()
    out: list[dict] = []
    for r in rows:
        t = r["titration_type"]
        c = float(r["concentration_m"])
        theory = float(r["actual_equivalence_volume_ml"])
        pred = float(r["predicted_equivalence_volume_ml"])
        manual = endpoints[(t, round(c, 2))]
        out.append({
            "titration_type": t,
            "type_label": TYPE_LABEL[t],
            "concentration_M": c,
            "condition": f"{TYPE_LABEL[t]} {c:.2f} M",
            "theoretical_ml": theory,
            "smart_predicted_ml": pred,
            "smart_signed_error_ml": pred - theory,
            "smart_abs_error_ml": abs(pred - theory),
            "smart_abs_percentage_error": abs(pred - theory) / theory * 100.0,
            "manual_endpoint_ml": manual,
            "manual_signed_error_ml": manual - theory,
            "manual_abs_error_ml": abs(manual - theory),
            "manual_abs_percentage_error": abs(manual - theory) / theory * 100.0,
        })
    out.sort(key=lambda r: (TYPE_ORDER.index(r["titration_type"]), r["concentration_M"]))
    return out


def metrics(actual: np.ndarray, predicted: np.ndarray) -> tuple[float, float, float]:
    err = predicted - actual
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mape = float(np.mean(np.abs(err) / actual) * 100.0)
    return mae, rmse, mape


def style_axis(ax, *, grid_axis="y") -> None:
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.8, alpha=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#94A3B8")
    ax.spines["bottom"].set_color("#94A3B8")


def save(fig, stem: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{stem}.png", bbox_inches="tight", facecolor="white")
    fig.savefig(OUT / f"{stem}.svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def figure_smart_vs_theory(runs: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(12.5, 8.3))
    y = np.arange(len(runs))[::-1]
    for yi, r in zip(y, runs):
        theory, pred = r["theoretical_ml"], r["smart_predicted_ml"]
        color = TYPE_COLOR[r["titration_type"]]
        ax.plot([theory, pred], [yi, yi], color="#94A3B8", linewidth=2.2, zorder=1)
        ax.scatter(theory, yi, s=95, facecolor="white", edgecolor=NAVY, linewidth=2, zorder=3)
        ax.scatter(pred, yi, s=105, color=color, edgecolor="white", linewidth=1.2, zorder=4)
        if r["smart_abs_percentage_error"] >= 5:
            ax.annotate(f"{r['smart_abs_percentage_error']:.2f}%", (pred, yi), xytext=(8, 0), textcoords="offset points", va="center", color=RED, fontweight="bold")
    ax.set_yticks(y, [r["condition"] for r in runs])
    ax.set_xlabel("당량점 부피 (mL)")
    ax.set_title("12회 적정 자료: 이론 당량점과 센서 융합 모델 추정값", loc="left", fontweight="bold", pad=16)
    ax.text(0, 1.01, "○ 이론값   ● 색상·열화상 융합 모델 추정값", transform=ax.transAxes, color=GRAY, fontsize=12)
    ax.set_xlim(17.5, 43.5)
    style_axis(ax, grid_axis="x")
    save(fig, "01_smart_theory_vs_prediction")


def figure_smart_error_by_run(runs: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(11.5, 8.8))
    y = np.arange(len(runs))[::-1]
    vals = np.array([r["smart_abs_percentage_error"] for r in runs])
    colors = [
        TYPE_COLOR[r["titration_type"]] if v < 5 else RED
        for r, v in zip(runs, vals)
    ]
    bars = ax.barh(y, vals, color=colors, height=0.66)
    for bar, v in zip(bars, vals):
        ax.text(
            v + 0.10,
            bar.get_y() + bar.get_height() / 2,
            f"{v:.2f}%",
            ha="left",
            va="center",
            fontsize=10,
            fontweight="bold" if v >= 5 else "normal",
            color=RED if v >= 5 else NAVY,
        )
    for level, color, label in [(1, "#94A3B8", "1%"), (2, ORANGE, "2%"), (5, RED, "5%")]:
        ax.axvline(level, color=color, linestyle="--", linewidth=1.2)
        ax.text(level + 0.05, len(runs) - 0.35, label, ha="left", va="top", color=color, fontsize=10)
    ax.set_yticks(y, [r["condition"] for r in runs])
    ax.set_xlabel("절대 상대오차 (%)")
    ax.set_title("12회 적정 자료의 조건별 센서 융합 모델 오차", loc="left", fontweight="bold", pad=14)
    ax.set_xlim(0, max(9.4, vals.max() + 0.8))
    style_axis(ax, grid_axis="x")
    save(fig, "02_smart_error_by_condition")


def figure_manual_vs_smart(runs: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(11.8, 9.0))
    y = np.arange(len(runs))[::-1]
    h = 0.36
    manual = np.array([r["manual_abs_percentage_error"] for r in runs])
    smart = np.array([r["smart_abs_percentage_error"] for r in runs])
    b1 = ax.barh(y + h / 2, manual, height=h, label="수동 적정", color="#64748B")
    b2 = ax.barh(y - h / 2, smart, height=h, label="비접촉 장치·센서 융합 ML", color=TEAL)
    for bars, vals in [(b1,manual),(b2,smart)]:
        for b,v in zip(bars,vals):
            if v>=3:
                ax.text(v + 0.10, b.get_y()+b.get_height()/2, f"{v:.2f}%", ha="left", va="center", fontsize=9, color=RED if v>=5 else NAVY)
    ax.axvline(5,color=RED,linestyle="--",linewidth=1.2,label="5% 기준선")
    ax.set_yticks(y, [r["condition"] for r in runs])
    ax.set_xlabel("절대 상대오차 (%)")
    ax.set_title("같은 12개 조건의 수동 적정과 비접촉 장치 추정 오차",loc="left",fontweight="bold",pad=14)
    ax.legend(frameon=False,ncol=3,loc="upper left")
    ax.set_xlim(0,max(9.4,smart.max()+0.8))
    style_axis(ax, grid_axis="x")
    save(fig,"03_manual_vs_smart_by_condition")


def figure_manual_theory_vs_endpoint(runs: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(12.5, 7.2))
    x = np.arange(len(runs))
    theory = np.array([r["theoretical_ml"] for r in runs])
    manual = np.array([r["manual_endpoint_ml"] for r in runs])
    ax.plot(x, theory, marker="o", linewidth=2.2, color=BLUE, label="기준 당량점")
    ax.plot(x, manual, marker="s", linewidth=2.2, color=ORANGE, label="수동 적정 종말점")
    ax.set_xticks(x, [r["condition"].replace(" ", "\n", 1) for r in runs])
    ax.set_ylabel("부피 (mL)")
    ax.set_title("수동 적정의 기준 당량점과 관찰 종말점", loc="left", fontweight="bold", pad=14)
    ax.legend(frameon=False, ncol=2, loc="upper left")
    ax.tick_params(axis="x", labelsize=9)
    style_axis(ax)
    save(fig, "10_manual_theory_vs_endpoint")


def figure_manual_signed_error(runs: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(12.5, 7.2))
    x = np.arange(len(runs))
    errors = np.array([r["manual_signed_error_ml"] for r in runs])
    colors = [TEAL if value >= 0 else ORANGE for value in errors]
    bars = ax.bar(x, errors, color=colors, width=0.68)
    ax.axhline(0, color=NAVY, linewidth=1.2)
    for bar, value in zip(bars, errors):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + (0.06 if value >= 0 else -0.08),
            f"{value:+.1f}",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=9,
        )
    ax.set_xticks(x, [r["condition"].replace(" ", "\n", 1) for r in runs])
    ax.set_ylabel("부호 오차 (mL)")
    ax.set_title("수동 적정의 조건별 부호 오차", loc="left", fontweight="bold", pad=14)
    ax.tick_params(axis="x", labelsize=9)
    style_axis(ax)
    save(fig, "11_manual_signed_error")


def build_method_rows(runs: list[dict]) -> list[dict]:
    actual=np.array([r["theoretical_ml"] for r in runs],dtype=float)
    manual=np.array([r["manual_endpoint_ml"] for r in runs],dtype=float)
    manual_mae,manual_rmse,manual_mape=metrics(actual,manual)
    overall={r["group"]:r for r in read_csv(OVERALL)}
    return [
        {"family":"수동","method":"수동 적정","mae_ml":manual_mae,"rmse_ml":manual_rmse,"mape_percent":manual_mape},
        {"family":"비ML","method":"색 최대 기울기","mae_ml":1.183,"rmse_ml":1.736,"mape_percent":4.673611},
        {"family":"비ML","method":"색·온도 임계값","mae_ml":2.033,"rmse_ml":3.308,"mape_percent":5.65},
        {"family":"ML","method":"ML 색상","mae_ml":float(overall["color_only"]["mae_ml"]),"rmse_ml":float(overall["color_only"]["rmse_ml"]),"mape_percent":float(overall["color_only"]["mape_percent"])},
        {"family":"ML","method":"ML 열화상","mae_ml":float(overall["thermal_only"]["mae_ml"]),"rmse_ml":float(overall["thermal_only"]["rmse_ml"]),"mape_percent":float(overall["thermal_only"]["mape_percent"])},
        {"family":"ML","method":"ML 색상+열화상","mae_ml":float(overall["color_thermal_fusion"]["mae_ml"]),"rmse_ml":float(overall["color_thermal_fusion"]["rmse_ml"]),"mape_percent":float(overall["color_thermal_fusion"]["mape_percent"])},
    ]


def figure_method_mape(rows: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(10.8, 6.5))
    methods=[r["method"] for r in rows][::-1]; vals=np.array([r["mape_percent"] for r in rows][::-1])
    families=[r["family"] for r in rows][::-1]
    colors=["#64748B" if f=="수동" else ORANGE if f=="비ML" else TEAL for f in families]
    colors[0]=BLUE  # fusion, reversed list
    y=np.arange(len(rows)); bars=ax.barh(y,vals,color=colors,height=0.66)
    for b,v in zip(bars,vals): ax.text(v+0.09,b.get_y()+b.get_height()/2,f"{v:.2f}%",va="center",fontsize=12,fontweight="bold" if v<=1.6 else "normal")
    ax.set_yticks(y,methods); ax.set_xlabel("MAPE (%)")
    ax.set_title("수동·비머신러닝·머신러닝 당량점 판정 성능",loc="left",fontweight="bold",pad=14)
    ax.text(
        0,
        -0.12,
        "머신러닝: 실험(run) 단위 leave-one-out 검증 · 현재 주입량은 모델 입력에서 제외",
        transform=ax.transAxes,
        color=GRAY,
        fontsize=10,
    )
    ax.axvline(5,color=RED,linestyle="--",linewidth=1.1)
    ax.text(5.05,len(rows)-0.35,"5%",color=RED,fontsize=10)
    ax.set_xlim(0,max(vals)+0.9); style_axis(ax,grid_axis="x")
    save(fig,"04_method_comparison_mape")


def figure_method_mae_rmse(rows: list[dict]) -> None:
    fig,axes=plt.subplots(1,2,figsize=(13.5,6.2),sharey=True)
    methods=[r["method"] for r in rows][::-1]; y=np.arange(len(rows))
    families=[r["family"] for r in rows][::-1]
    colors=["#64748B" if f=="수동" else ORANGE if f=="비ML" else TEAL for f in families]; colors[0]=BLUE
    for ax,key,title in zip(axes,["mae_ml","rmse_ml"],["평균 절대오차(MAE)","평균 제곱근 오차(RMSE)"]):
        vals=np.array([r[key] for r in rows][::-1]); bars=ax.barh(y,vals,color=colors,height=.64)
        for b,v in zip(bars,vals): ax.text(v+0.035,b.get_y()+b.get_height()/2,f"{v:.3f}",va="center",fontsize=10)
        ax.set_title(title,fontweight="bold"); ax.set_xlabel("오차 (mL)"); ax.set_yticks(y,methods); ax.set_xlim(0,max(vals)+0.45); style_axis(ax,grid_axis="x")
    fig.suptitle("판정 방식별 부피 오차 비교",x=.08,ha="left",fontweight="bold",fontsize=19)
    fig.subplots_adjust(top=.84,wspace=.18)
    save(fig,"05_method_comparison_mae_rmse")


def figure_modality() -> None:
    rows={r["group"]:r for r in read_csv(OVERALL)}
    keys=["color_only","thermal_only","color_thermal_fusion"]
    labels=["색상","열화상","색상+열화상"]
    colors=["#E11D48","#0EA5E9",TEAL]
    fig,axes=plt.subplots(1,2,figsize=(12,5.6))
    for ax,metric,title,unit in [(axes[0],"mape_percent","MAPE","%"),(axes[1],"mae_ml","MAE","mL")]:
        vals=np.array([float(rows[k][metric]) for k in keys]); bars=ax.bar(labels,vals,color=colors,width=.62)
        for b,v in zip(bars,vals): ax.text(b.get_x()+b.get_width()/2,v+max(vals)*.035,f"{v:.2f}{unit}",ha="center",fontweight="bold")
        ax.set_title(title,fontweight="bold"); ax.set_ylabel(f"{title} ({unit})"); ax.set_ylim(0,max(vals)*1.22); style_axis(ax)
    fig.suptitle("현재 주입량을 제외한 센서 입력 구성별 성능",x=.08,ha="left",fontweight="bold",fontsize=19)
    fig.text(
        .08,
        .01,
        "실험(run) 단위 leave-one-out 검증. 색상 단독 1.55%와 융합 1.52%의 차이는 0.03%p로 작다.",
        color=GRAY,
        fontsize=11,
    )
    fig.subplots_adjust(top=.82,bottom=.15,wspace=.28)
    save(fig,"06_sensor_modality_comparison")


def figure_typewise() -> None:
    rows=read_csv(TYPEWISE); by={r["titration_type"]:r for r in rows}; labels=[TYPE_LABEL[t] for t in TYPE_ORDER]
    vals=np.array([float(by[t]["mape_percent_on_available_type_runs"]) for t in TYPE_ORDER]); colors=[TYPE_COLOR[t] for t in TYPE_ORDER]
    fig,ax=plt.subplots(figsize=(9.8,5.7)); bars=ax.bar(labels,vals,color=colors,width=.65)
    for b,v in zip(bars,vals): ax.text(b.get_x()+b.get_width()/2,v+.09,f"{v:.2f}%",ha="center",fontweight="bold")
    ax.axhline(5,color=RED,linestyle="--",linewidth=1.2); ax.text(3.48,5.08,"5%",ha="right",color=RED)
    ax.set_ylabel("MAPE (%)"); ax.set_title("적정 종류별 색상·열화상 융합 모델 오차",loc="left",fontweight="bold",pad=14); ax.set_ylim(0,5.7); style_axis(ax)
    save(fig,"07_fusion_typewise_mape")


def figure_repeatability() -> None:
    vals=np.array([.0824,.0851,.0889]); mean=float(vals.mean()); sd=float(vals.std(ddof=1)); cv=sd/mean*100
    fig,ax=plt.subplots(figsize=(9.2,5.8)); x=np.arange(1,4)
    ax.plot(x,vals,color=BLUE,linewidth=2.4,marker="o",markersize=9)
    ax.axhline(mean,color=TEAL,linestyle="--",linewidth=2,label=f"평균 {mean:.4f} M")
    for xi,v in zip(x,vals): ax.text(xi,v+.00025,f"{v:.4f} M",ha="center",fontweight="bold")
    ax.set_xticks(x,["1회","2회","3회"]); ax.set_ylabel("환산 농도 (M)")
    ax.set_title("동일 용액 3회 반복 측정",loc="left",fontweight="bold",pad=14)
    ax.text(.02,.95,f"표본 표준편차 {sd:.4f} M   ·   변동계수 {cv:.2f}%",transform=ax.transAxes,va="top",color=GRAY)
    ax.set_ylim(.0805,.0907); ax.legend(frameon=False,loc="lower right"); style_axis(ax)
    save(fig,"08_repeatability_three_runs")


def figure_throughput() -> None:
    fig,ax=plt.subplots(figsize=(8.8,5.7))
    x=[0,1]; mid=[(3.10+4.60)/2,25.0]; yerr=[[mid[0]-3.10,0],[4.60-mid[0],0]]
    ax.errorbar([0],[mid[0]],yerr=[[mid[0]-3.10],[4.60-mid[0]]],fmt='o',markersize=11,color=ORANGE,ecolor=ORANGE,capsize=9,linewidth=3,label="초기 3.10~4.60행/s")
    ax.scatter([1],[25],s=150,color=TEAL,zorder=3,label="개선 후 25.0행/s")
    ax.plot([0,1],[mid[0],25],color="#CBD5E1",linewidth=2,zorder=1)
    ax.text(0,4.95,"3.10~4.60",ha="center",color=ORANGE,fontweight="bold")
    ax.text(1,25.7,"25.0",ha="center",color=TEAL,fontweight="bold")
    ax.axhline(25,color=BLUE,linestyle="--",linewidth=1.2); ax.text(1.28,25,"0.04초 간격 입력",va="center",ha="right",color=BLUE)
    ax.set_xticks(x,["초기 구조\n미리보기·기록 결합","개선 구조\n대기열 기반 기록"]); ax.set_ylabel("CSV 기록 속도 (행/s)")
    ax.set_title("CSV 저장 구조 개선 전후 처리 경로 시험",loc="left",fontweight="bold",pad=14)
    ax.text(
        0,
        -0.17,
        "개선 후 값은 0.04초 간격의 시험 입력을 순서대로 저장한 처리 경로 결과이며, 새 습식 실험 결과는 아니다.",
        transform=ax.transAxes,
        color=GRAY,
        fontsize=10,
    )
    ax.set_xlim(-.45,1.45); ax.set_ylim(0,29); style_axis(ax)
    save(fig,"09_csv_recording_throughput")


def write_caption_guide(method_rows: list[dict]) -> None:
    manual = next(row for row in method_rows if row["family"] == "수동")
    captions = f"""# 보고서 수정용 그래프 삽입 안내

모든 그래프는 현재 주입량을 머신러닝 특징에서 제외한 센서 전용 결과를 사용한다. PNG는 Word 삽입용, SVG는 고해상도 편집·인쇄용이다.

1. `01_smart_theory_vs_prediction`: 12회 적정 자료의 이론 당량점과 융합 모델 추정값. 12회 결과표 바로 뒤.
2. `02_smart_error_by_condition`: 조건별 절대 상대오차와 1·2·5% 기준선. 실패 조건 분석 절.
3. `03_manual_vs_smart_by_condition`: 같은 조건의 수동 적정값과 센서 융합 모델 추정 오차. 두 방식 직접 비교 절.
4. `04_method_comparison_mape`: 수동, 비ML 2종, ML 3종의 MAPE. 머신러닝 효과를 설명하는 핵심 그래프.
5. `05_method_comparison_mae_rmse`: 같은 6개 방식의 MAE·RMSE. 표의 보조 그래프.
6. `06_sensor_modality_comparison`: 색상·열화상·융합 모델 비교. 열화상의 실제 기여 해석 절.
7. `07_fusion_typewise_mape`: 네 적정 종류별 융합 모델 MAPE. 반응계별 화학적 해석 절.
8. `08_repeatability_three_runs`: 동일 용액 3회 환산 농도와 변동계수. 반복성 절.
9. `09_csv_recording_throughput`: 초기 3.10~4.60행/s에서 25.0행/s로 개선된 CSV 처리 경로 시험. 제작 오류·개선 절. 개선 후 수치는 0.04초 간격 시험 입력 결과이며 새 습식 실험 결과로 표현하지 않는다.

## 최종 보고서 우선순위

본문 필수는 01, 02, 04, 06, 08, 09이다. 03, 05, 07은 지면에 따라 본문 또는 부록에 배치한다.

## 수치 검산

- 수동 적정 12회: MAE {manual["mae_ml"]:.3f} mL, RMSE {manual["rmse_ml"]:.3f} mL, MAPE {manual["mape_percent"]:.2f}%.
- 색상·열화상 융합 모델 12회: MAE 0.476 mL, RMSE 0.831 mL, MAPE 1.52%.
- 융합 모델 조건별 오차: 1% 이내 7/12회, 2% 이내 10/12회, 5% 이내 11/12회.
- 센서 구성별 MAPE: 색상 1.55%, 열화상 3.66%, 색상+열화상 1.52%.
- 비머신러닝 기준선 MAPE: 색 최대 기울기 4.67%, 색·온도 임계값 5.65%.

센서 융합 모델은 수동 적정보다 MAPE가 0.48%p 낮았으며, 머신러닝 수치는 12개 실험을 run 단위로 분리한 leave-one-out 평가 결과이다.
"""
    (OUT / "README.md").write_text(captions, encoding="utf-8")


def main() -> None:
    setup_font(); OUT.mkdir(parents=True, exist_ok=True); SOURCE.mkdir(parents=True, exist_ok=True)
    runs=ordered_runs(); method_rows=build_method_rows(runs)
    write_csv(SOURCE/"smart_manual_run_comparison.csv",runs,list(runs[0].keys()))
    write_csv(SOURCE/"method_comparison.csv",method_rows,["family","method","mae_ml","rmse_ml","mape_percent"])
    write_csv(SOURCE/"csv_recording_throughput.csv",[
        {"stage":"initial","min_rows_per_s":3.10,"max_rows_per_s":4.60,"representative_rows_per_s":3.85},
        {"stage":"queue_based","min_rows_per_s":25.0,"max_rows_per_s":25.0,"representative_rows_per_s":25.0},
    ],["stage","min_rows_per_s","max_rows_per_s","representative_rows_per_s"])
    figure_smart_vs_theory(runs); figure_smart_error_by_run(runs); figure_manual_vs_smart(runs)
    figure_manual_theory_vs_endpoint(runs); figure_manual_signed_error(runs)
    figure_method_mape(method_rows); figure_method_mae_rmse(method_rows); figure_modality(); figure_typewise(); figure_repeatability(); figure_throughput(); write_caption_guide(method_rows)
    print(f"created figures in {OUT}")

if __name__ == "__main__":
    main()
