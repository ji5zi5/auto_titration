"""Post-hoc typewise ML model selection for auto-titration equivalence prediction.

This script reads model-zoo prediction artifacts and selects the best model/spec
inside each titration type, mirroring the old curve evaluator's typewise-selected
summary.  The result is intentionally labelled post-hoc because model/spec choice
is made after seeing held-out fold metrics.
"""

from __future__ import annotations

import csv
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_titrator.ml_curve_equivalence import run_level_metrics

DEFAULT_OUTPUT_DIR = Path("data/ml/posthoc_typewise_model_selection")
MODEL_ZOO_RUNS = {
    "strict_no_progress": Path("data/ml/model_zoo_equivalence_current"),
    "with_progress_protocol": Path("data/ml/model_zoo_equivalence_with_progress"),
}
OLD_CURVE_COMPARISON = Path("data/ml/curve_equivalence_current/model_algorithm_comparison.csv")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"required CSV artifact does not exist: {path}")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _float(value: Any, default: float = math.inf) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _prediction_files(root: Path) -> Iterable[Path]:
    prediction_dir = root / "predictions"
    if not prediction_dir.exists():
        raise FileNotFoundError(f"required prediction artifact directory does not exist: {prediction_dir}")
    files = sorted(prediction_dir.rglob("*.csv"))
    if not files:
        raise FileNotFoundError(f"no prediction CSV files found under: {prediction_dir}")
    yield from files


def _load_predictions(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _prediction_files(root):
        for row in _read_csv(path):
            out = dict(row)
            out["artifact_path"] = str(path)
            rows.append(out)
    return rows


def _spec_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("claim_scope") or ""),
        str(row.get("model") or ""),
        str(row.get("params_json") or ""),
        str(row.get("feature_set") or ""),
        str(row.get("candidate_mode") or ""),
    )


def _metric_row(
    *,
    dataset: str,
    selection_scope: str,
    titration_type: str,
    spec_key: tuple[str, str, str, str, str],
    predictions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    metrics = run_level_metrics(predictions)
    claim_scope, model, params_json, feature_set, candidate_mode = spec_key
    return {
        "dataset": dataset,
        "selection_scope": selection_scope,
        "titration_type": titration_type,
        "claim_scope": claim_scope,
        "model": model,
        "params_json": params_json,
        "feature_set": feature_set,
        "candidate_mode": candidate_mode,
        "run_count": metrics.get("run_count", 0),
        "mae_ml": metrics.get("mae_ml", 0.0),
        "median_abs_error_ml": metrics.get("median_abs_error_ml", 0.0),
        "rmse_ml": metrics.get("rmse_ml", 0.0),
        "bias_ml": metrics.get("bias_ml", 0.0),
        "mae_percent_of_equivalence": metrics.get("mae_percent_of_equivalence", 0.0),
        "concentration_mae_percent": metrics.get("concentration_mae_percent", 0.0),
        "within_0p5ml_rate": metrics.get("within_0.5ml_rate", 0.0),
        "within_1p0ml_rate": metrics.get("within_1.0ml_rate", 0.0),
        "within_2pct_rate": metrics.get("within_2pct_rate", 0.0),
        "within_5pct_rate": metrics.get("within_5pct_rate", 0.0),
    }


def _select_typewise(
    dataset: str,
    predictions: Sequence[Mapping[str, Any]],
    *,
    selection_scope: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    rows = list(predictions)
    if selection_scope == "headline_only":
        rows = [row for row in rows if row.get("claim_scope") == "headline"]
    elif selection_scope == "all_model_zoo":
        rows = rows
    else:
        raise ValueError(f"unknown selection_scope: {selection_scope}")

    by_type_spec: dict[tuple[str, tuple[str, str, str, str, str]], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_type_spec[(str(row.get("titration_type") or ""), _spec_key(row))].append(row)

    selected_rows: list[dict[str, Any]] = []
    selected_predictions: list[dict[str, Any]] = []
    for (titration_type, spec_key), subset in by_type_spec.items():
        if not titration_type:
            continue
        selected_rows.append(
            _metric_row(
                dataset=dataset,
                selection_scope=selection_scope,
                titration_type=titration_type,
                spec_key=spec_key,
                predictions=subset,
            )
        )
    best_by_type: dict[str, dict[str, Any]] = {}
    for row in selected_rows:
        t = str(row["titration_type"])
        old = best_by_type.get(t)
        if old is None or (_float(row["mae_ml"]), _float(row["rmse_ml"]), str(row["model"])) < (
            _float(old["mae_ml"]),
            _float(old["rmse_ml"]),
            str(old["model"]),
        ):
            best_by_type[t] = row

    for best in best_by_type.values():
        key = (
            str(best["claim_scope"]),
            str(best["model"]),
            str(best["params_json"]),
            str(best["feature_set"]),
            str(best["candidate_mode"]),
        )
        for row in rows:
            if str(row.get("titration_type") or "") == best["titration_type"] and _spec_key(row) == key:
                out = dict(row)
                out["dataset"] = dataset
                out["selection_scope"] = selection_scope
                selected_predictions.append(out)

    overall_metrics = run_level_metrics(selected_predictions)
    overall = {
        "dataset": dataset,
        "selection_scope": selection_scope,
        "selection_is_posthoc": "yes",
        "type_count": len(best_by_type),
        "run_count": overall_metrics.get("run_count", 0),
        "mae_ml": overall_metrics.get("mae_ml", 0.0),
        "median_abs_error_ml": overall_metrics.get("median_abs_error_ml", 0.0),
        "rmse_ml": overall_metrics.get("rmse_ml", 0.0),
        "bias_ml": overall_metrics.get("bias_ml", 0.0),
        "mae_percent_of_equivalence": overall_metrics.get("mae_percent_of_equivalence", 0.0),
        "concentration_mae_percent": overall_metrics.get("concentration_mae_percent", 0.0),
        "within_0p5ml_rate": overall_metrics.get("within_0.5ml_rate", 0.0),
        "within_1p0ml_rate": overall_metrics.get("within_1.0ml_rate", 0.0),
        "within_2pct_rate": overall_metrics.get("within_2pct_rate", 0.0),
        "within_5pct_rate": overall_metrics.get("within_5pct_rate", 0.0),
    }
    best_rows = [best_by_type[key] for key in sorted(best_by_type)]
    return best_rows, selected_predictions, overall


def _old_curve_rows() -> list[dict[str, Any]]:
    rows = _read_csv(OLD_CURVE_COMPARISON)
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("scope") == "overall" and row.get("feature_set") == "typewise selected":
            out.append(
                {
                    "dataset": "old_curve_equivalence_current",
                    "selection_scope": "old_typewise_selected",
                    "selection_is_posthoc": "yes",
                    "type_count": "4",
                    "run_count": row.get("run_count", ""),
                    "model": row.get("model", ""),
                    "mae_ml": row.get("mae_ml", ""),
                    "median_abs_error_ml": row.get("median_abs_error_ml", ""),
                    "rmse_ml": row.get("rmse_ml", ""),
                    "bias_ml": row.get("bias_ml", ""),
                    "mae_percent_of_equivalence": row.get("mae_percent_of_equivalence", ""),
                    "concentration_mae_percent": row.get("concentration_mae_percent", ""),
                    "within_0p5ml_rate": row.get("within_0.5ml_rate", ""),
                    "within_1p0ml_rate": row.get("within_1.0ml_rate", ""),
                    "within_2pct_rate": row.get("within_2pct_rate", ""),
                    "within_5pct_rate": row.get("within_5pct_rate", ""),
                }
            )
    return sorted(out, key=lambda row: _float(row.get("mae_ml")))


def _render_doc(overall_rows: Sequence[Mapping[str, Any]], typewise_rows: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# 타입별 사후 선택 ML 모델 비교",
        "",
        "이 문서는 예전 curve 모델의 `typewise selected`와 같은 방식으로, 적정 종류별로 가장 낮은 MAE를 보인 모델/feature 조합을 고른 결과이다.",
        "단, 이 선택은 held-out fold 성능을 확인한 뒤 가장 좋은 조합을 고르는 방식이므로 실제 일반화 성능보다 낙관적으로 보일 수 있다.",
        "`with_progress_protocol` 결과는 진행률과 전체 주입량 비율 후보를 포함한 비엄격 프로토콜 보조 수치이며, 센서만으로 실시간 배포 가능한 성능으로 해석하면 안 된다.",
        "따라서 이 결과는 최종 후보 선정용 탐색 결과이며, 단일 고정 모델을 미리 정하고 평가한 엄격 성능과 반드시 구분해야 한다.",
        "",
        "## 전체 비교",
        "| 데이터셋 | 선택 범위 | MAE mL | RMSE mL | 상대오차 MAE | 설명 |",
        "|---|---|---:|---:|---:|---|",
    ]
    labels = {
        ("strict_no_progress", "headline_only"): "진행률 제거, headline 모델만",
        ("strict_no_progress", "all_model_zoo"): "진행률 제거, 전체 model zoo",
        ("with_progress_protocol", "headline_only"): "진행률 포함, headline 모델만",
        ("with_progress_protocol", "all_model_zoo"): "진행률 포함, 전체 model zoo",
        ("old_curve_equivalence_current", "old_typewise_selected"): "예전 curve typewise selected",
    }
    display_rows: list[Mapping[str, Any]] = []
    old_curve_rows = [row for row in overall_rows if row.get("dataset") == "old_curve_equivalence_current"]
    if old_curve_rows:
        display_rows.append(min(old_curve_rows, key=lambda row: _float(row.get("mae_ml"))))
    display_rows.extend(row for row in overall_rows if row.get("dataset") != "old_curve_equivalence_current")
    for row in sorted(display_rows, key=lambda r: _float(r.get("mae_ml"))):
        dataset = str(row.get("dataset", ""))
        scope = str(row.get("selection_scope", ""))
        model_suffix = f" ({row.get('model')})" if row.get("model") else ""
        lines.append(
            f"| {dataset} | {scope} | {float(row.get('mae_ml') or 0):.6f} | "
            f"{float(row.get('rmse_ml') or 0):.6f} | {float(row.get('mae_percent_of_equivalence') or 0):.2f}% | "
            f"{labels.get((dataset, scope), '')}{model_suffix} |"
        )
    lines.extend([
        "",
        "## 타입별 선택 결과",
        "| 데이터셋 | 선택 범위 | 적정 종류 | 선택 모델 | feature set | MAE mL | 상대오차 MAE |",
        "|---|---|---|---|---|---:|---:|",
    ])
    for row in sorted(typewise_rows, key=lambda r: (str(r.get("dataset")), str(r.get("selection_scope")), str(r.get("titration_type")))):
        lines.append(
            f"| {row.get('dataset')} | {row.get('selection_scope')} | {row.get('titration_type')} | "
            f"{row.get('model')} | {row.get('feature_set')} | {float(row.get('mae_ml') or 0):.6f} | "
            f"{float(row.get('mae_percent_of_equivalence') or 0):.2f}% |"
        )
    lines.extend([
        "",
        "## 해석",
        "- 타입별 사후 선택을 하면 진행률 포함 새 model-zoo도 단일 최고 모델보다 낮은 오차를 낸다.",
        "- 그래도 예전 curve 결과가 더 낮은 이유는 예전 후보 생성과 feature set 구조가 더 강하게 프로토콜 비율 후보를 활용했기 때문이다.",
        "- 이 표는 모델 선택과 성능 보고에 같은 작은 데이터셋을 사용하므로 낙관적이다.",
        "- 보고서에는 이 결과를 `타입별 최적 조합 선정 결과` 또는 `탐색적 최종 후보`라고 표시하고, 확정 일반화 성능처럼 쓰지 않는 것이 안전하다.",
    ])
    return "\n".join(lines) + "\n"


def _write_svg(overall_rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    rows = [row for row in overall_rows if row.get("dataset") != "old_curve_equivalence_current" or row.get("model") == "Extra Trees Regression"]
    rows = sorted(rows, key=lambda r: _float(r.get("mae_ml")))
    width, height = 1100, 520
    margin_l, margin_r, margin_t, margin_b = 260, 40, 50, 95
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b
    max_mae = max((_float(row.get("mae_ml"), 0) for row in rows), default=1.0) * 1.12
    bar_h = min(44, plot_h / max(1, len(rows)) - 8)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="32" y="34" font-family="Pretendard, Arial, sans-serif" font-size="24" font-weight="700" fill="#111827">타입별 사후 선택 모델 MAE 비교</text>',
    ]
    for i, row in enumerate(rows):
        y = margin_t + i * (bar_h + 8) + 24
        mae = _float(row.get("mae_ml"), 0)
        bar_w = plot_w * mae / max_mae
        label = f"{row.get('dataset')} · {row.get('selection_scope')}"
        color = "#2563eb" if row.get("dataset") == "with_progress_protocol" else "#64748b"
        if row.get("dataset") == "old_curve_equivalence_current":
            color = "#16a34a"
        if row.get("dataset") == "strict_no_progress":
            color = "#dc2626"
        parts.append(f'<text x="32" y="{y + bar_h*0.65:.1f}" font-family="Pretendard, Arial, sans-serif" font-size="15" fill="#111827">{label}</text>')
        parts.append(f'<rect x="{margin_l}" y="{y}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="8" fill="{color}"/>')
        parts.append(f'<text x="{margin_l + bar_w + 10:.1f}" y="{y + bar_h*0.65:.1f}" font-family="Pretendard, Arial, sans-serif" font-size="15" font-weight="700" fill="#111827">{mae:.2f} mL</text>')
    parts.append(f'<text x="{margin_l}" y="{height-28}" font-family="Pretendard, Arial, sans-serif" font-size="13" fill="#6b7280">낮을수록 좋음. 진행률 포함값은 비엄격 프로토콜 보조 + post-hoc 탐색 결과라 실제 일반화 성능보다 낙관적일 수 있음.</text>')
    parts.append('</svg>')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def main() -> int:
    out_dir = DEFAULT_OUTPUT_DIR
    all_typewise_rows: list[dict[str, Any]] = []
    all_selected_predictions: list[dict[str, Any]] = []
    overall_rows: list[dict[str, Any]] = []
    for dataset, root in MODEL_ZOO_RUNS.items():
        predictions = _load_predictions(root)
        if not predictions:
            continue
        for scope in ("headline_only", "all_model_zoo"):
            type_rows, selected_predictions, overall = _select_typewise(dataset, predictions, selection_scope=scope)
            all_typewise_rows.extend(type_rows)
            all_selected_predictions.extend(selected_predictions)
            overall_rows.append(overall)
    overall_rows.extend(_old_curve_rows())

    _write_csv(out_dir / "typewise_selected_models.csv", all_typewise_rows)
    _write_csv(out_dir / "selected_predictions.csv", all_selected_predictions)
    _write_csv(out_dir / "overall_comparison.csv", overall_rows)
    Path("docs").mkdir(exist_ok=True)
    Path("docs/ml_posthoc_typewise_model_selection.md").write_text(_render_doc(overall_rows, all_typewise_rows), encoding="utf-8")
    _write_svg(overall_rows, Path("docs/poster_visuals/17_posthoc_typewise_model_selection_mae.svg"))
    print({
        "overall_rows": len(overall_rows),
        "typewise_rows": len(all_typewise_rows),
        "selected_predictions": len(all_selected_predictions),
        "best": min(overall_rows, key=lambda r: _float(r.get("mae_ml"))) if overall_rows else {},
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
