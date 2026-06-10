"""Compare equivalence-volume ML with and without injected-volume information.

This script is intentionally a reporting/diagnostic evaluator for the current
12 experiment CSVs.  It separates three claim scopes:

* strict_sensor_no_injection_volume: uses run-level visible/thermal statistics
  and no injected-volume/time/protocol columns.
* sensor_plus_type_no_injection_volume: adds titration type one-hot metadata but
  still excludes injected-volume/time/protocol columns.
* protocol_assisted_uses_final_max_volume: uses final maximum injected volume
  after the experiment.  This can be very accurate on the current protocol, but
  it is not live sensor-only performance and must not be reported that way.

The held-out theoretical equivalence volume is never passed as an input feature.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_titrator.ml_curve_equivalence import _to_float, run_level_metrics
from auto_titrator.ml_typewise_eval import CsvRun, load_runs
from tools import protocol_calibrated_equivalence as pce

DEFAULT_INPUT_DIR = Path("머신러닝용 파일모음")
DEFAULT_OUTPUT_DIR = Path("data/ml/injection_ablation_search")
DEFAULT_DOC_PATH = Path("docs/ml_injection_ablation_search.md")
DEFAULT_SVG_PATH = Path("docs/poster_visuals/19_injection_ablation_mape.svg")

TITRATION_TYPES = (
    "strong_acid_strong_base",
    "strong_acid_weak_base",
    "weak_acid_strong_base",
    "weak_acid_weak_base",
)

SENSOR_PREFIXES = ("visible_", "thermal_roi_", "thermal_raw_", "thermal_raw_roi_")
SENSOR_EXCLUDE_TOKENS = (
    "_x",
    "_y",
    "_width",
    "_height",
    "capture_",
    "frame_rate",
    "conversion_",
    "matrix_shape",
    "source",
    "calibrated",
    "rotation",
)
FORBIDDEN_FEATURE_TOKENS = (
    "equivalence",
    "distance_to_",
    "time_to_",
    "label",
    "target",
    "actual_",
    "predicted_",
    "estimated_",
    "sample_concentration",
    "concentration_m",
    "pump_",
    "injected_volume",
    "time_s",
    "elapsed",
    "row_count",
    "csv_row_index",
    "frame_id",
)


@dataclass(frozen=True)
class RunFeatures:
    run_path: str
    titration_type: str
    concentration_m: float
    actual_equivalence_volume_ml: float
    run_volume_max_ml: float
    row_count: int
    sensor_features: dict[str, float]


def _safe_number(value: Any) -> float | None:
    number = _to_float(value)
    if number is None or not math.isfinite(float(number)):
        return None
    return float(number)


def _is_sensor_column(column: str) -> bool:
    if not column.startswith(SENSOR_PREFIXES):
        return False
    lowered = column.lower()
    if any(token in lowered for token in FORBIDDEN_FEATURE_TOKENS):
        return False
    if any(token in lowered for token in SENSOR_EXCLUDE_TOKENS):
        return False
    return True


def _column_values(run: CsvRun, column: str) -> list[float]:
    values: list[float] = []
    for row in run.rows:
        value = _safe_number(row.get(column))
        if value is not None:
            values.append(value)
    return values


def _summarize_values(prefix: str, values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {}
    arr = np.array(values, dtype=float)
    diffs = np.diff(arr) if len(arr) > 1 else np.array([0.0], dtype=float)
    return {
        f"{prefix}__first": float(arr[0]),
        f"{prefix}__last": float(arr[-1]),
        f"{prefix}__mean": float(np.mean(arr)),
        f"{prefix}__std": float(np.std(arr)),
        f"{prefix}__min": float(np.min(arr)),
        f"{prefix}__max": float(np.max(arr)),
        f"{prefix}__range": float(np.max(arr) - np.min(arr)),
        f"{prefix}__p05": float(np.percentile(arr, 5)),
        f"{prefix}__p50": float(np.percentile(arr, 50)),
        f"{prefix}__p95": float(np.percentile(arr, 95)),
        f"{prefix}__last_minus_first": float(arr[-1] - arr[0]),
        f"{prefix}__mean_abs_step_change": float(np.mean(np.abs(diffs))),
        f"{prefix}__max_abs_step_change": float(np.max(np.abs(diffs))),
    }


def _sensor_features(run: CsvRun) -> dict[str, float]:
    columns = sorted({column for row in run.rows for column in row.keys() if _is_sensor_column(column)})
    features: dict[str, float] = {}
    for column in columns:
        features.update(_summarize_values(column, _column_values(run, column)))
    return features


def _records_from_runs(runs: Sequence[CsvRun]) -> list[RunFeatures]:
    records: list[RunFeatures] = []
    for run in runs:
        volumes = [_safe_number(row.get("injected_volume_ml")) for row in run.rows]
        numeric_volumes = [value for value in volumes if value is not None]
        if not numeric_volumes:
            raise ValueError(f"run has no injected_volume_ml values: {run.path}")
        records.append(
            RunFeatures(
                run_path=str(run.path),
                titration_type=run.titration_type,
                concentration_m=float(run.concentration_m),
                actual_equivalence_volume_ml=float(run.theoretical_equivalence_volume_ml),
                run_volume_max_ml=max(numeric_volumes),
                row_count=len(run.rows),
                sensor_features=_sensor_features(run),
            )
        )
    return records


def _all_sensor_feature_names(records: Sequence[RunFeatures]) -> list[str]:
    names: set[str] = set()
    for record in records:
        names.update(record.sensor_features.keys())
    return sorted(names)


def _feature_vector(record: RunFeatures, feature_names: Sequence[str], mode: str) -> list[float]:
    values: list[float] = []
    if mode in {"sensor_no_volume", "sensor_type_no_volume", "max_volume_type_sensor"}:
        values.extend(record.sensor_features.get(name, 0.0) for name in feature_names)
    if mode in {"sensor_type_no_volume", "max_volume_type", "max_volume_type_sensor"}:
        values.extend(1.0 if record.titration_type == name else 0.0 for name in TITRATION_TYPES)
    if mode in {"max_volume_type", "max_volume_type_sensor"}:
        values.append(record.run_volume_max_ml)
    return [float(value) if math.isfinite(float(value)) else 0.0 for value in values]


def _model_factories(train_size: int) -> list[tuple[str, Callable[[], Any], str]]:
    try:
        from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor, RandomForestRegressor
        from sklearn.linear_model import Ridge
        from sklearn.neighbors import KNeighborsRegressor
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.svm import SVR
    except Exception as exc:  # pragma: no cover - environment compatibility guard
        raise RuntimeError(f"scikit-learn is required for injection ablation search: {exc!r}") from exc

    k1 = 1
    k3 = max(1, min(3, train_size))
    k5 = max(1, min(5, train_size))
    return [
        ("ridge_standard", lambda: make_pipeline(StandardScaler(), Ridge(alpha=1.0)), "regularized_linear"),
        ("svr_rbf", lambda: make_pipeline(StandardScaler(), SVR(C=10.0, epsilon=0.05, gamma="scale")), "kernel_regression"),
        ("knn1", lambda: make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=k1, weights="distance")), "nearest_protocol_lookup_diagnostic"),
        ("knn3", lambda: make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=k3, weights="distance")), "nearest_regression"),
        ("knn5", lambda: make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=k5, weights="distance")), "nearest_regression"),
        (
            "random_forest",
            lambda: RandomForestRegressor(n_estimators=300, random_state=42, min_samples_leaf=1),
            "tree_ensemble",
        ),
        (
            "extra_trees",
            lambda: ExtraTreesRegressor(n_estimators=300, random_state=42, min_samples_leaf=1),
            "tree_ensemble",
        ),
        (
            "gradient_boosting",
            lambda: GradientBoostingRegressor(random_state=42, n_estimators=100, learning_rate=0.05, max_depth=2),
            "boosted_trees",
        ),
    ]


def _claim_scope_for_mode(mode: str, model_name: str) -> str:
    if mode in {"sensor_no_volume", "sensor_type_no_volume"}:
        return "post_experiment_sensor_summary_no_injection_volume"
    if model_name == "knn1":
        return "protocol_assisted_final_max_volume_nearest_lookup_diagnostic"
    return "protocol_assisted_uses_final_max_volume"


def _warning_for_mode(mode: str, model_name: str) -> str:
    if mode in {"sensor_no_volume", "sensor_type_no_volume"}:
        return "excludes injected volume, time, row count, sample concentration, and equivalence/label columns"
    if model_name == "knn1":
        return "diagnostic only: final max volume plus tiny 12-run protocol makes nearest-neighbor behave like a protocol lookup"
    return "not live sensor-only and not nested-selected: uses final maximum injected volume; treat as posthoc diagnostic model search"


def _model_search_scope_for_mode(mode: str) -> str:
    if mode in {"sensor_no_volume", "sensor_type_no_volume"}:
        return "strict_ablation_current_12_run_loo_not_nested_selected"
    return "posthoc_model_search_not_nested_current_12_run_loo"


def _evaluate_mode_model(records: Sequence[RunFeatures], mode: str, model_name: str, feature_names: Sequence[str], factory: Callable[[], Any], family: str) -> list[dict[str, Any]]:
    predictions: list[dict[str, Any]] = []
    for test in records:
        train = [record for record in records if record.run_path != test.run_path]
        x_train = np.array([_feature_vector(record, feature_names, mode) for record in train], dtype=float)
        y_train = np.array([record.actual_equivalence_volume_ml for record in train], dtype=float)
        x_test = np.array([_feature_vector(test, feature_names, mode)], dtype=float)
        model = factory()
        model.fit(x_train, y_train)
        prediction = float(model.predict(x_test)[0])
        error = prediction - test.actual_equivalence_volume_ml
        predictions.append(
            {
                "mode": mode,
                "model": model_name,
                "model_family": family,
                "run_path": test.run_path,
                "titration_type": test.titration_type,
                "held_out_concentration_m": round(test.concentration_m, 6),
                "actual_equivalence_volume_ml": round(test.actual_equivalence_volume_ml, 6),
                "predicted_equivalence_volume_ml": round(prediction, 6),
                "absolute_error_ml": round(abs(error), 6),
                "absolute_error_percent_of_equivalence": round(abs(error) / test.actual_equivalence_volume_ml * 100.0, 6),
                "signed_error_ml": round(error, 6),
                "run_volume_max_ml": round(test.run_volume_max_ml, 6) if mode.startswith("max_volume") else "excluded",
                "row_count": "excluded",
                "feature_count": len(_feature_vector(test, feature_names, mode)),
                "claim_scope": _claim_scope_for_mode(mode, model_name),
                "model_search_scope": _model_search_scope_for_mode(mode),
                "diagnostic_only": "yes" if mode.startswith("max_volume") else "no",
                "warning": _warning_for_mode(mode, model_name),
                "validation": "leave_one_run_out_current_12_csvs",
            }
        )
    return predictions


def _overall_row(predictions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = run_level_metrics(predictions)
    first = predictions[0]
    mode = str(first["mode"])
    model_name = str(first["model"])
    return {
        "mode": mode,
        "model": model_name,
        "model_family": first.get("model_family", ""),
        "claim_scope": first.get("claim_scope", ""),
        "model_search_scope": first.get("model_search_scope", ""),
        "diagnostic_only": first.get("diagnostic_only", ""),
        "run_count": metrics.get("run_count", 0),
        "mae_ml": metrics.get("mae_ml", 0.0),
        "median_abs_error_ml": metrics.get("median_abs_error_ml", 0.0),
        "rmse_ml": metrics.get("rmse_ml", 0.0),
        "mape_percent": metrics.get("mae_percent_of_equivalence", 0.0),
        "concentration_mae_percent": metrics.get("concentration_mae_percent", 0.0),
        "within_2pct_rate": metrics.get("within_2pct_rate", 0.0),
        "within_5pct_rate": metrics.get("within_5pct_rate", 0.0),
        "target_mape_under_5pct": "yes" if float(metrics.get("mae_percent_of_equivalence", 999.0)) <= 5.0 else "no",
        "warning": first.get("warning", ""),
    }


def _typewise_rows(predictions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_type: dict[str, list[Mapping[str, Any]]] = {}
    for row in predictions:
        by_type.setdefault(str(row["titration_type"]), []).append(row)
    rows: list[dict[str, Any]] = []
    first = predictions[0]
    for titration_type, subset in sorted(by_type.items()):
        metrics = run_level_metrics(subset)
        rows.append(
            {
                "mode": first["mode"],
                "model": first["model"],
                "titration_type": titration_type,
                "run_count": metrics.get("run_count", 0),
                "mae_ml": metrics.get("mae_ml", 0.0),
                "rmse_ml": metrics.get("rmse_ml", 0.0),
                "mape_percent": metrics.get("mae_percent_of_equivalence", 0.0),
                "within_5pct_rate": metrics.get("within_5pct_rate", 0.0),
            }
        )
    return rows


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _best_rows(overall_rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    buckets = {
        "best_sensor_no_volume": [row for row in overall_rows if str(row["mode"]) in {"sensor_no_volume", "sensor_type_no_volume"}],
        "best_protocol_final_volume": [row for row in overall_rows if str(row["mode"]).startswith("max_volume")],
        "best_protocol_non_knn1": [
            row for row in overall_rows if str(row["mode"]).startswith("max_volume") and str(row["model"]) != "knn1"
        ],
    }
    return {key: min(rows, key=lambda row: float(row["mape_percent"])) for key, rows in buckets.items() if rows}


def _render_doc(overall_rows: Sequence[Mapping[str, Any]], typewise_rows: Sequence[Mapping[str, Any]], selected_predictions: Sequence[Mapping[str, Any]], protocol_summary: Mapping[str, Any]) -> str:
    best = _best_rows(overall_rows)
    best_sensor = best["best_sensor_no_volume"]
    best_protocol = best["best_protocol_final_volume"]
    best_non_knn = best["best_protocol_non_knn1"]
    nested_protocol = next(row for row in protocol_summary["overall"] if row["dataset"] == "nested_protocol_calibrated_max_volume")
    fixed_protocol = next(row for row in protocol_summary["overall"] if row["dataset"] == "fixed_alpha_0p25_protocol_calibrated")

    lines = [
        "# 주입량 사용 여부별 당량점 예측 ablation",
        "",
        "## 핵심 결론",
        f"- 주입량을 전혀 쓰지 않은 센서 요약 모델의 현재 최저 MAPE는 {float(best_sensor['mape_percent']):.2f}%이다. 따라서 현재 12개 CSV만으로는 무주입량 5% 이내를 달성하지 못했다.",
        f"- 최종 최대 주입량을 쓰는 protocol-assisted 모델은 훨씬 낮아진다. 진단용 최저 모델은 {best_protocol['model']}로 MAPE {float(best_protocol['mape_percent']):.2f}%이다.",
        f"- 다만 {best_protocol['model']} 결과는 현재 12-run 프로토콜에서 최종 주입량 패턴을 거의 lookup처럼 쓰는 성격이 강하므로, 보고서의 안전한 메인 결과는 nested protocol 보정 MAPE {float(nested_protocol['mape_percent']):.2f}%로 두는 편이 낫다.",
        "- 모든 결과는 leave-one-run-out으로 계산했고, held-out run의 정답 부피는 입력 feature로 넣지 않았다.",
        "",
        "## 전체 모델 비교",
        "| 구분 | 모델 | MAE mL | RMSE mL | MAPE | 5% 이내 | 해석 |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    display_order = sorted(overall_rows, key=lambda row: (0 if str(row["mode"]).startswith("sensor") else 1, float(row["mape_percent"])))
    for row in display_order:
        if row["model"] not in {"extra_trees", "gradient_boosting", "knn1", "knn3", "knn5", "random_forest", "ridge_standard"}:
            continue
        mode_label = {
            "sensor_no_volume": "센서만",
            "sensor_type_no_volume": "센서+적정종류",
            "max_volume_type": "최대주입량+적정종류",
            "max_volume_type_sensor": "최대주입량+센서+적정종류",
        }.get(str(row["mode"]), str(row["mode"]))
        warning = str(row.get("warning", ""))
        short_warning = "무주입량" if "excludes" in warning else ("진단용 lookup 성격" if row["model"] == "knn1" else "post-experiment")
        lines.append(
            f"| {mode_label} | {row['model']} | {float(row['mae_ml']):.3f} | {float(row['rmse_ml']):.3f} | {float(row['mape_percent']):.2f}% | {row['target_mape_under_5pct']} | {short_warning} |"
        )
    lines.extend(
        [
            "",
            "## 안전하게 보고서에 쓸 수 있는 값",
            f"- 무주입량: 현재 best는 {best_sensor['model']} / {best_sensor['mode']}이며 MAPE {float(best_sensor['mape_percent']):.2f}%로 실패.",
            f"- 주입량 사용: fixed alpha protocol 보정 MAPE {float(fixed_protocol['mape_percent']):.2f}%, nested protocol 보정 MAPE {float(nested_protocol['mape_percent']):.2f}%.",
            f"- 더 공격적인 진단 모델: {best_non_knn['model']}는 MAPE {float(best_non_knn['mape_percent']):.2f}%까지 내려간다. 단, 최종 주입량 패턴과 12개뿐인 데이터에 강하게 의존하므로 일반화 성능 주장에는 쓰지 않는 것이 안전하다.",
            "",
            "## 적정 종류별 nested protocol 보정 한계",
            "| 적정 종류 | MAE mL | MAPE |",
            "|---|---:|---:|",
        ]
    )
    for row in protocol_summary["typewise"]:
        if row["dataset"] != "nested_protocol_calibrated_max_volume":
            continue
        lines.append(f"| {row['titration_type']} | {float(row['mae_ml']):.3f} | {float(row['mape_percent']):.2f}% |")
    lines.extend(
        [
            "",
            "## 주의 문구",
            "최대 주입량을 쓰는 모델은 실험이 끝난 뒤 알 수 있는 정보를 사용한다. 그래서 실시간 자동 정지 성능이나 순수 색·온도 센서 성능으로 해석하면 안 된다. 본 연구에서는 자동 정지를 목표로 하지 않으므로, 실험 후 당량점·농도 계산 보정 모델로 제한해서 해석한다.",
            "",
            "## 생성 파일",
            "- `data/ml/injection_ablation_search/model_comparison.csv`",
            "- `data/ml/injection_ablation_search/typewise_comparison.csv`",
            "- `data/ml/injection_ablation_search/selected_predictions.csv`",
            "- `docs/poster_visuals/19_injection_ablation_mape.svg`",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_svg(overall_rows: Sequence[Mapping[str, Any]], protocol_summary: Mapping[str, Any], path: Path) -> None:
    best = _best_rows(overall_rows)
    nested = next(row for row in protocol_summary["overall"] if row["dataset"] == "nested_protocol_calibrated_max_volume")
    bars = [
        ("무주입량 best", float(best["best_sensor_no_volume"]["mape_percent"]), "#dc2626"),
        ("프로토콜 보정", float(nested["mape_percent"]), "#16a34a"),
        ("최대주입량 진단 best", float(best["best_protocol_final_volume"]["mape_percent"]), "#2563eb"),
    ]
    width, height = 980, 360
    max_value = max(value for _, value, _ in bars) * 1.12
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="34" y="44" font-family="Pretendard, Arial, sans-serif" font-size="27" font-weight="700" fill="#111827">주입량 사용 여부에 따른 MAPE</text>',
        '<line x1="230" y1="78" x2="230" y2="278" stroke="#e5e7eb"/>',
    ]
    for i, (label, value, color) in enumerate(bars):
        y = 90 + i * 68
        w = 610 * value / max_value if max_value else 0
        parts.append(f'<text x="34" y="{y+24}" font-family="Pretendard, Arial, sans-serif" font-size="18" fill="#111827">{label}</text>')
        parts.append(f'<rect x="230" y="{y}" width="{w:.1f}" height="34" rx="9" fill="{color}"/>')
        parts.append(f'<text x="{240+w:.1f}" y="{y+24}" font-family="Pretendard, Arial, sans-serif" font-size="18" font-weight="700" fill="#111827">{value:.2f}%</text>')
    x5 = 230 + 610 * 5.0 / max_value
    parts.append(f'<line x1="{x5:.1f}" y1="80" x2="{x5:.1f}" y2="288" stroke="#111827" stroke-dasharray="5 5"/>')
    parts.append(f'<text x="{x5+8:.1f}" y="304" font-family="Pretendard, Arial, sans-serif" font-size="14" fill="#111827">5% 목표선</text>')
    parts.append('<text x="34" y="338" font-family="Pretendard, Arial, sans-serif" font-size="14" fill="#6b7280">최대주입량 모델은 post-experiment/protocol-assisted 결과이며 센서-only 성능이 아니다.</text>')
    parts.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def run(
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    doc_path: Path | None = None,
    svg_path: Path | None = None,
    protocol_output_dir: Path | None = None,
    protocol_doc_path: Path | None = None,
    protocol_svg_path: Path | None = None,
) -> dict[str, Any]:
    runs = load_runs(input_dir)
    records = _records_from_runs(runs)
    feature_names = _all_sensor_feature_names(records)
    modes = ("sensor_no_volume", "sensor_type_no_volume", "max_volume_type", "max_volume_type_sensor")

    all_predictions: list[dict[str, Any]] = []
    overall_rows: list[dict[str, Any]] = []
    typewise_rows: list[dict[str, Any]] = []
    for mode in modes:
        for model_name, factory, family in _model_factories(len(records) - 1):
            predictions = _evaluate_mode_model(records, mode, model_name, feature_names, factory, family)
            all_predictions.extend(predictions)
            overall_rows.append(_overall_row(predictions))
            typewise_rows.extend(_typewise_rows(predictions))

    best = _best_rows(overall_rows)
    selected_pairs = {
        (best["best_sensor_no_volume"]["mode"], best["best_sensor_no_volume"]["model"]),
        (best["best_protocol_final_volume"]["mode"], best["best_protocol_final_volume"]["model"]),
        (best["best_protocol_non_knn1"]["mode"], best["best_protocol_non_knn1"]["model"]),
    }
    selected_predictions = [row for row in all_predictions if (row["mode"], row["model"]) in selected_pairs]

    protocol_summary = pce.run(
        input_dir=input_dir,
        output_dir=protocol_output_dir or output_dir / "protocol_calibrated_reference",
        doc_path=protocol_doc_path,
        svg_path=protocol_svg_path,
    )

    _write_csv(output_dir / "model_comparison.csv", sorted(overall_rows, key=lambda row: float(row["mape_percent"])))
    _write_csv(output_dir / "typewise_comparison.csv", typewise_rows)
    _write_csv(output_dir / "all_predictions.csv", all_predictions)
    _write_csv(output_dir / "selected_predictions.csv", selected_predictions)
    if doc_path is not None:
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(_render_doc(overall_rows, typewise_rows, selected_predictions, protocol_summary), encoding="utf-8")
    if svg_path is not None:
        _write_svg(overall_rows, protocol_summary, svg_path)

    summary = {
        "run_count": len(records),
        "sensor_feature_count": len(feature_names),
        "best": best,
        "protocol_calibrated_reference": protocol_summary["overall"],
        "output_dir": str(output_dir),
        "protocol_output_dir": str(protocol_output_dir or output_dir / "protocol_calibrated_reference"),
        "claim": {
            "no_injection_volume_under_5pct": float(best["best_sensor_no_volume"]["mape_percent"]) <= 5.0,
            "protocol_assisted_diagnostic_under_5pct": float(best["best_protocol_final_volume"]["mape_percent"]) <= 5.0,
            "protocol_assisted_nested_reference_under_5pct": any(
                row.get("dataset") == "nested_protocol_calibrated_max_volume"
                and float(row.get("mape_percent", 999.0)) <= 5.0
                for row in protocol_summary["overall"]
            ),
            "protocol_assisted_under_5pct": any(
                row.get("dataset") == "nested_protocol_calibrated_max_volume"
                and float(row.get("mape_percent", 999.0)) <= 5.0
                for row in protocol_summary["overall"]
            ),
            "recommended_report_metric": "nested_protocol_calibrated_max_volume",
            "diagnostic_best_model_warning": "The 0.16% gradient-boosting result is posthoc model search on the current 12-run leave-one-out set; use it only as diagnostic evidence, not as a generalization claim.",
            "strict_warning": "Protocol-assisted results use final max injected volume and are not live sensor-only.",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    summary = run(
        doc_path=DEFAULT_DOC_PATH,
        svg_path=DEFAULT_SVG_PATH,
        protocol_output_dir=Path("data/ml/protocol_calibrated_equivalence"),
        protocol_doc_path=pce.DEFAULT_DOC_PATH,
        protocol_svg_path=pce.DEFAULT_SVG_PATH,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
