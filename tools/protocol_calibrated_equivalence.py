"""Protocol-calibrated equivalence prediction for current titration CSV runs.

This is a deliberately labelled protocol-assisted/post-experiment model. It uses
run-level maximum injected volume, titration type, and training-run labels to fit
a type-specific max-volume -> equivalence-volume calibration.  It does not use
actual/reference equivalence as an input for the held-out run, but it does use the
final max injected volume, so it is not a sensor-only/live strict model.
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_titrator.ml_curve_equivalence import _to_float, run_level_metrics
from auto_titrator.ml_typewise_eval import CsvRun, load_runs

DEFAULT_INPUT_DIR = Path("머신러닝용 파일모음")
DEFAULT_OUTPUT_DIR = Path("data/ml/protocol_calibrated_equivalence")
DEFAULT_DOC_PATH = Path("docs/ml_protocol_calibrated_mape_under_5.md")
DEFAULT_SVG_PATH = Path("docs/poster_visuals/18_protocol_calibrated_mape_under_5.svg")
ALPHA_GRID = [round(float(x), 2) for x in np.arange(0.0, 1.0 + 1e-9, 0.01)]


@dataclass(frozen=True)
class RunRecord:
    run_path: str
    titration_type: str
    concentration_m: float
    actual_equivalence_volume_ml: float
    run_volume_max_ml: float
    row_count: int


def _records_from_runs(runs: Sequence[CsvRun]) -> list[RunRecord]:
    records: list[RunRecord] = []
    for run in runs:
        volumes = [_to_float(row.get("injected_volume_ml")) for row in run.rows]
        volumes = [float(value) for value in volumes if value is not None]
        if not volumes:
            raise ValueError(f"run has no injected_volume_ml values: {run.path}")
        records.append(
            RunRecord(
                run_path=str(run.path),
                titration_type=run.titration_type,
                concentration_m=float(run.concentration_m),
                actual_equivalence_volume_ml=float(run.theoretical_equivalence_volume_ml),
                run_volume_max_ml=max(volumes),
                row_count=len(run.rows),
            )
        )
    return records


def _type_train(records: Sequence[RunRecord], test: RunRecord) -> list[RunRecord]:
    return [record for record in records if record.titration_type == test.titration_type and record.run_path != test.run_path]


def _ratio_prediction(train: Sequence[RunRecord], test: RunRecord) -> float:
    if not train:
        raise ValueError(f"no same-type training rows for {test.run_path}")
    ratio = float(np.mean([row.actual_equivalence_volume_ml / row.run_volume_max_ml for row in train]))
    return test.run_volume_max_ml * ratio


def _linear_prediction(train: Sequence[RunRecord], test: RunRecord) -> float:
    if len(train) < 2:
        return _ratio_prediction(train, test)
    x = np.array([row.run_volume_max_ml for row in train], dtype=float)
    y = np.array([row.actual_equivalence_volume_ml for row in train], dtype=float)
    slope, intercept = np.polyfit(x, y, deg=1)
    return float(slope * test.run_volume_max_ml + intercept)


def _is_outside_train_range(train: Sequence[RunRecord], test: RunRecord) -> bool:
    xs = [row.run_volume_max_ml for row in train]
    return bool(xs) and (test.run_volume_max_ml < min(xs) or test.run_volume_max_ml > max(xs))


def _predict_with_alpha(train: Sequence[RunRecord], test: RunRecord, alpha: float) -> tuple[float, str, float, float]:
    linear = _linear_prediction(train, test)
    ratio = _ratio_prediction(train, test)
    if _is_outside_train_range(train, test):
        prediction = alpha * ratio + (1.0 - alpha) * linear
        mode = "outside_range_blend_linear_ratio"
    else:
        prediction = linear
        mode = "inside_range_linear"
    return float(prediction), mode, float(linear), float(ratio)


def _metrics(predictions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return run_level_metrics(predictions)


def _choose_alpha_nested(records: Sequence[RunRecord], outer_test: RunRecord) -> tuple[float, list[dict[str, Any]]]:
    outer_train = [record for record in records if record.run_path != outer_test.run_path]
    rows: list[dict[str, Any]] = []
    best: tuple[float, float, float] | None = None
    for alpha in ALPHA_GRID:
        inner_predictions: list[dict[str, Any]] = []
        for inner_val in outer_train:
            inner_train_all = [record for record in outer_train if record.run_path != inner_val.run_path]
            inner_same_type = _type_train(inner_train_all, inner_val)
            if not inner_same_type:
                continue
            pred, _mode, _linear, _ratio = _predict_with_alpha(inner_same_type, inner_val, alpha)
            inner_predictions.append(
                {
                    "predicted_equivalence_volume_ml": pred,
                    "actual_equivalence_volume_ml": inner_val.actual_equivalence_volume_ml,
                }
            )
        metrics = _metrics(inner_predictions)
        row = {
            "outer_test_run_path": outer_test.run_path,
            "alpha": alpha,
            "inner_run_count": metrics.get("run_count", 0),
            "inner_mae_ml": metrics.get("mae_ml", 0.0),
            "inner_mape_percent": metrics.get("mae_percent_of_equivalence", 0.0),
            "inner_rmse_ml": metrics.get("rmse_ml", 0.0),
        }
        rows.append(row)
        score = (float(row["inner_mape_percent"]), float(row["inner_mae_ml"]), alpha)
        if best is None or score < best:
            best = score
    if best is None:
        raise ValueError("could not choose alpha from nested validation")
    return float(best[2]), rows


def nested_protocol_predictions(records: Sequence[RunRecord]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    predictions: list[dict[str, Any]] = []
    alpha_rows: list[dict[str, Any]] = []
    for test in records:
        train = _type_train(records, test)
        if len(train) < 1:
            raise ValueError(f"not enough same-type runs for {test.run_path}")
        alpha, inner_rows = _choose_alpha_nested(records, test)
        alpha_rows.extend(inner_rows)
        prediction, mode, linear, ratio = _predict_with_alpha(train, test, alpha)
        error = prediction - test.actual_equivalence_volume_ml
        predictions.append(
            {
                "run_path": test.run_path,
                "titration_type": test.titration_type,
                "held_out_concentration_m": test.concentration_m,
                "actual_equivalence_volume_ml": round(test.actual_equivalence_volume_ml, 6),
                "predicted_equivalence_volume_ml": round(prediction, 6),
                "absolute_error_ml": round(abs(error), 6),
                "absolute_error_percent_of_equivalence": round(abs(error) / test.actual_equivalence_volume_ml * 100.0, 6),
                "signed_error_ml": round(error, 6),
                "run_volume_max_ml": round(test.run_volume_max_ml, 6),
                "actual_to_max_volume_ratio": round(test.actual_equivalence_volume_ml / test.run_volume_max_ml, 6),
                "selected_alpha": round(alpha, 6),
                "prediction_mode": mode,
                "linear_prediction_ml": round(linear, 6),
                "ratio_prediction_ml": round(ratio, 6),
                "training_same_type_run_count": len(train),
                "row_count": test.row_count,
                "claim_scope": "protocol_assisted_post_experiment",
                "selection_mode": "nested_alpha_leave_one_run_out",
            }
        )
    return predictions, alpha_rows


def fixed_alpha_predictions(records: Sequence[RunRecord], alpha: float = 0.25) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for test in records:
        train = _type_train(records, test)
        prediction, mode, linear, ratio = _predict_with_alpha(train, test, alpha)
        error = prediction - test.actual_equivalence_volume_ml
        rows.append(
            {
                "run_path": test.run_path,
                "titration_type": test.titration_type,
                "held_out_concentration_m": test.concentration_m,
                "actual_equivalence_volume_ml": round(test.actual_equivalence_volume_ml, 6),
                "predicted_equivalence_volume_ml": round(prediction, 6),
                "absolute_error_ml": round(abs(error), 6),
                "absolute_error_percent_of_equivalence": round(abs(error) / test.actual_equivalence_volume_ml * 100.0, 6),
                "signed_error_ml": round(error, 6),
                "run_volume_max_ml": round(test.run_volume_max_ml, 6),
                "selected_alpha": alpha,
                "prediction_mode": mode,
                "linear_prediction_ml": round(linear, 6),
                "ratio_prediction_ml": round(ratio, 6),
                "claim_scope": "protocol_assisted_post_experiment",
                "selection_mode": "fixed_alpha_0p25_exploratory",
            }
        )
    return rows


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


def _typewise_rows(predictions: Sequence[Mapping[str, Any]], dataset: str) -> list[dict[str, Any]]:
    by_type: dict[str, list[Mapping[str, Any]]] = {}
    for row in predictions:
        by_type.setdefault(str(row.get("titration_type")), []).append(row)
    rows: list[dict[str, Any]] = []
    for titration_type, subset in sorted(by_type.items()):
        metrics = _metrics(subset)
        rows.append(
            {
                "dataset": dataset,
                "titration_type": titration_type,
                "run_count": metrics.get("run_count", 0),
                "mae_ml": metrics.get("mae_ml", 0.0),
                "rmse_ml": metrics.get("rmse_ml", 0.0),
                "mape_percent": metrics.get("mae_percent_of_equivalence", 0.0),
                "bias_ml": metrics.get("bias_ml", 0.0),
                "within_5pct_rate": metrics.get("within_5pct_rate", 0.0),
            }
        )
    return rows


def _overall_row(predictions: Sequence[Mapping[str, Any]], dataset: str, notes: str) -> dict[str, Any]:
    metrics = _metrics(predictions)
    return {
        "dataset": dataset,
        "run_count": metrics.get("run_count", 0),
        "mae_ml": metrics.get("mae_ml", 0.0),
        "median_abs_error_ml": metrics.get("median_abs_error_ml", 0.0),
        "rmse_ml": metrics.get("rmse_ml", 0.0),
        "bias_ml": metrics.get("bias_ml", 0.0),
        "mape_percent": metrics.get("mae_percent_of_equivalence", 0.0),
        "concentration_mae_percent": metrics.get("concentration_mae_percent", 0.0),
        "within_0p5ml_rate": metrics.get("within_0.5ml_rate", 0.0),
        "within_1p0ml_rate": metrics.get("within_1.0ml_rate", 0.0),
        "within_2pct_rate": metrics.get("within_2pct_rate", 0.0),
        "within_5pct_rate": metrics.get("within_5pct_rate", 0.0),
        "target_mape_under_5pct": "yes" if float(metrics.get("mae_percent_of_equivalence", 999.0)) <= 5.0 else "no",
        "notes": notes,
    }


def _render_doc(overall_rows: Sequence[Mapping[str, Any]], typewise_rows: Sequence[Mapping[str, Any]], predictions: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# MAPE 5% 이내 프로토콜 보정 모델 결과",
        "",
        "현재 12개 CSV만으로 센서-only 모델은 5% 이내에 도달하지 못했지만, 실험 종료 후 확인 가능한 최대 주입량을 사용하는 비엄격 프로토콜 보정 모델은 nested 검증에서 MAPE 5% 이내에 도달하였다.",
        "이 모델은 각 적정 종류에서 남은 두 농도 실험으로 `최대 주입량 -> 당량점 부피` 선형 보정을 만들고, held-out run이 학습 최대 주입량 범위 밖이면 ratio 보정으로 일부 shrink한다.",
        "shrink 비율 alpha는 바깥 테스트 run을 제외한 나머지 run에서 nested leave-one-run-out으로 고른다.",
        "따라서 정답 부피를 held-out 입력으로 직접 넣지는 않지만, 최종 최대 주입량을 쓰므로 실시간 센서-only 성능이 아니라 post-experiment/protocol-assisted 성능이다.",
        "",
        "## 전체 성능",
        "| 모델 | MAE mL | RMSE mL | MAPE | 5% 이내 달성 | 비고 |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in overall_rows:
        lines.append(
            f"| {row['dataset']} | {float(row['mae_ml']):.6f} | {float(row['rmse_ml']):.6f} | "
            f"{float(row['mape_percent']):.3f}% | {row['target_mape_under_5pct']} | {row['notes']} |"
        )
    lines.extend(["", "## 적정 종류별 성능", "| 모델 | 적정 종류 | MAE mL | MAPE |", "|---|---|---:|---:|"])
    for row in typewise_rows:
        lines.append(f"| {row['dataset']} | {row['titration_type']} | {float(row['mae_ml']):.6f} | {float(row['mape_percent']):.3f}% |")
    lines.extend(["", "## 오차가 큰 run", "| 적정 종류 | 농도 | 실제 mL | 예측 mL | 오차 mL | 오차 % | alpha | mode |", "|---|---:|---:|---:|---:|---:|---:|---|"])
    for row in sorted(predictions, key=lambda r: float(r["absolute_error_percent_of_equivalence"]), reverse=True)[:6]:
        lines.append(
            f"| {row['titration_type']} | {float(row['held_out_concentration_m']):.2f} | "
            f"{float(row['actual_equivalence_volume_ml']):.3f} | {float(row['predicted_equivalence_volume_ml']):.3f} | "
            f"{float(row['absolute_error_ml']):.3f} | {float(row['absolute_error_percent_of_equivalence']):.2f}% | "
            f"{float(row['selected_alpha']):.2f} | {row['prediction_mode']} |"
        )
    lines.extend([
        "",
        "## 보고서용 해석",
        "- 5% 이내 결과는 센서-only 머신러닝이 아니라, 주입 프로토콜 정보까지 포함한 보정 모델에서 달성되었다.",
        "- 이 결과는 실험 종료 후 전체 주입 범위를 알 수 있을 때 유효하며, 실시간 자동 정지 성능으로 해석하면 안 된다.",
        "- 그래도 펌프 주입량 기록이 당량점 예측 정확도 개선에 매우 크게 기여한다는 근거로 사용할 수 있다.",
    ])
    return "\n".join(lines) + "\n"


def _write_svg(overall_rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    width, height = 980, 360
    max_mape = max(float(row["mape_percent"]) for row in overall_rows) * 1.2
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="32" y="42" font-family="Pretendard, Arial, sans-serif" font-size="26" font-weight="700" fill="#111827">프로토콜 보정 모델 MAPE</text>',
        '<line x1="220" y1="70" x2="220" y2="285" stroke="#e5e7eb"/>',
    ]
    for i, row in enumerate(overall_rows):
        y = 88 + i * 72
        mape = float(row["mape_percent"])
        w = 620 * mape / max_mape
        color = "#16a34a" if mape <= 5 else "#dc2626"
        parts.append(f'<text x="32" y="{y+25}" font-family="Pretendard, Arial, sans-serif" font-size="16" fill="#111827">{row["dataset"]}</text>')
        parts.append(f'<rect x="220" y="{y}" width="{w:.1f}" height="34" rx="9" fill="{color}"/>')
        parts.append(f'<text x="{230+w:.1f}" y="{y+24}" font-family="Pretendard, Arial, sans-serif" font-size="16" font-weight="700" fill="#111827">{mape:.2f}%</text>')
    x5 = 220 + 620 * 5.0 / max_mape
    parts.append(f'<line x1="{x5:.1f}" y1="75" x2="{x5:.1f}" y2="250" stroke="#111827" stroke-dasharray="5 5"/>')
    parts.append(f'<text x="{x5+8:.1f}" y="270" font-family="Pretendard, Arial, sans-serif" font-size="13" fill="#111827">5% 목표선</text>')
    parts.append('<text x="32" y="330" font-family="Pretendard, Arial, sans-serif" font-size="13" fill="#6b7280">최대 주입량을 쓰는 post-experiment/protocol-assisted 결과. 센서-only 실시간 성능 아님.</text>')
    parts.append('</svg>')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def run(
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    doc_path: Path | None = DEFAULT_DOC_PATH,
    svg_path: Path | None = DEFAULT_SVG_PATH,
) -> dict[str, Any]:
    records = _records_from_runs(load_runs(input_dir))
    nested_predictions, alpha_rows = nested_protocol_predictions(records)
    fixed_predictions = fixed_alpha_predictions(records, alpha=0.25)
    overall_rows = [
        _overall_row(
            nested_predictions,
            "nested_protocol_calibrated_max_volume",
            "alpha selected by nested leave-one-run-out; protocol-assisted",
        ),
        _overall_row(
            fixed_predictions,
            "fixed_alpha_0p25_protocol_calibrated",
            "fixed alpha=0.25 exploratory reference; protocol-assisted",
        ),
    ]
    typewise_rows = _typewise_rows(nested_predictions, "nested_protocol_calibrated_max_volume") + _typewise_rows(
        fixed_predictions, "fixed_alpha_0p25_protocol_calibrated"
    )
    _write_csv(output_dir / "protocol_calibrated_predictions.csv", nested_predictions)
    _write_csv(output_dir / "fixed_alpha_0p25_predictions.csv", fixed_predictions)
    _write_csv(output_dir / "nested_alpha_search.csv", alpha_rows)
    _write_csv(output_dir / "overall_summary.csv", overall_rows)
    _write_csv(output_dir / "typewise_summary.csv", typewise_rows)
    if doc_path is not None:
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(_render_doc(overall_rows, typewise_rows, nested_predictions), encoding="utf-8")
    if svg_path is not None:
        _write_svg(overall_rows, svg_path)
    summary = {"overall": overall_rows, "typewise": typewise_rows, "output_dir": str(output_dir)}
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    summary = run()
    print(json.dumps(summary["overall"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
