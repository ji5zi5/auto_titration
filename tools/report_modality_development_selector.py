#!/usr/bin/env python3
"""Report sensor-modality comparison using the established development selector.

This deliberately mirrors the historical ``current_volume_no_progress``
development analysis:

* one LORO prediction per CSV run for every registered frame-zone candidate;
* the same model hyperparameters, zone windows, scopes, and aggregation modes;
* post-hoc best-method selection separately within each titration type;
* no claim of nested or external validation.

The visible-only and thermal-only arms remove the other sensor modality while
holding the historical non-sensor control columns fixed.  The fusion arm is the
locked historical 1.27% reference and is checked by recomputing its four chosen
source methods from the same feature-column manifest.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import resource
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.ml_typewise_eval import CsvRun, load_runs  # noqa: E402
from tools import train_equivalence_current_volume as trainer  # noqa: E402

DEFAULT_INPUT_DIR = Path("머신러닝용 파일모음")
DEFAULT_REFERENCE_DIR = Path("data/ml/current_volume_no_progress")
DEFAULT_OUTPUT_DIR = Path("data/ml/report_modality_development_selector")
GROUPS = ("color_only", "thermal_only", "color_thermal_fusion")
RANDOM_STATE = trainer.RANDOM_STATE


@dataclass(frozen=True, order=True)
class CandidateSignature:
    model_name: str
    scope: str
    window_ml: float


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = sorted({str(key) for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                    if isinstance(value, (list, dict))
                    else value
                    for key, value in row.items()
                }
            )


def load_reference_feature_columns(reference_dir: str | Path) -> list[str]:
    path = Path(reference_dir) / "selected_frame_feature_columns.csv"
    rows = _load_csv(path)
    columns = [str(row.get("feature") or "").strip() for row in rows]
    columns = [column for column in columns if column]
    if "injected_volume_ml" not in columns:
        raise ValueError(f"{path}: injected_volume_ml is missing")
    trainer.assert_no_forbidden_features(columns)
    return columns


def select_group_columns(
    reference_columns: Sequence[str],
    group: str,
    *,
    include_current_volume_feature: bool = True,
) -> list[str]:
    """Keep historical shared controls fixed and ablate only sensor modalities."""

    if group not in GROUPS:
        raise ValueError(f"unknown group: {group}")
    color = {column for column in reference_columns if column.startswith("visible_")}
    thermal = {column for column in reference_columns if column.startswith("thermal_")}
    shared = [
        column
        for column in reference_columns
        if column not in color and column not in thermal
    ]
    allowed = set(shared)
    if group in {"color_only", "color_thermal_fusion"}:
        allowed.update(color)
    if group in {"thermal_only", "color_thermal_fusion"}:
        allowed.update(thermal)
    selected = [column for column in reference_columns if column in allowed]
    if not include_current_volume_feature:
        selected = [
            column for column in selected if column != "injected_volume_ml"
        ]
    trainer.assert_no_forbidden_features(selected)
    if group == "color_only" and any(column.startswith("thermal_") for column in selected):
        raise ValueError("thermal feature leaked into color-only arm")
    if group == "thermal_only" and any(column.startswith("visible_") for column in selected):
        raise ValueError("visible feature leaked into thermal-only arm")
    return selected


def shared_control_columns(reference_columns: Sequence[str]) -> list[str]:
    return [
        column
        for column in reference_columns
        if not column.startswith(("visible_", "thermal_"))
    ]


def build_group_records(
    runs: Sequence[CsvRun],
    columns: Sequence[str],
    *,
    grid_ml: float,
) -> list[dict[str, Any]]:
    trainer.assert_no_forbidden_features(columns)
    records: list[dict[str, Any]] = []
    for run in runs:
        for row in trainer.volume_resampled_rows(run, grid_ml=grid_ml):
            volume = trainer.safe_float(row.get("injected_volume_ml"))
            if volume is None:
                continue
            records.append(
                {
                    "run_path": trainer.run_id(run),
                    "titration_type": run.titration_type,
                    "concentration_m": run.concentration_m,
                    "actual_ml": run.theoretical_equivalence_volume_ml,
                    "current_volume_ml": volume,
                    "features": trainer.row_to_feature_dict(row, columns),
                }
            )
    return records


def parse_candidate_key(method_key: str) -> tuple[CandidateSignature, str]:
    parts = method_key.split(":")
    if len(parts) < 4 or parts[0] != "frame_zone_classifier":
        raise ValueError(f"not a frame-zone method key: {method_key}")
    model_name = parts[1]
    if parts[2] in {"all_types", "same_type"}:
        scope = parts[2]
        window_part = parts[3]
        mode = parts[4]
    else:
        scope = "all_types"
        window_part = parts[2]
        mode = parts[3]
    if not window_part.startswith("window"):
        raise ValueError(f"missing window in method key: {method_key}")
    return CandidateSignature(model_name, scope, float(window_part.removeprefix("window"))), mode


def load_candidate_registry(
    reference_dir: str | Path,
) -> dict[CandidateSignature, dict[str, list[str]]]:
    """Load the exact historical frame-zone candidate key set."""

    rows = _load_csv(Path(reference_dir) / "all_predictions_merged.csv")
    registry: dict[CandidateSignature, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for method_key in sorted(
        {
            str(row.get("method_key") or "")
            for row in rows
            if str(row.get("method_key") or "").startswith("frame_zone_classifier:")
        }
    ):
        signature, mode = parse_candidate_key(method_key)
        registry[signature][mode].append(method_key)
    if not registry:
        raise ValueError("reference contains no frame-zone candidates")
    return {
        signature: {mode: list(keys) for mode, keys in modes.items()}
        for signature, modes in registry.items()
    }


def _bounded_model(model_name: str, train_size: int):
    from sklearn.base import clone

    models = dict(trainer.frame_model_specs("classifier", train_size))
    if model_name not in models:
        raise ValueError(f"unknown historical model: {model_name}")
    model = clone(models[model_name])
    params = model.get_params(deep=True)
    updates = {
        key: 1
        for key, value in params.items()
        if (key == "n_jobs" or key.endswith("__n_jobs")) and value is not None
    }
    if updates:
        model.set_params(**updates)
    return model


def _evaluate_signature(
    signature: CandidateSignature,
    modes_to_keys: Mapping[str, Sequence[str]],
    runs: Sequence[CsvRun],
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    from threadpoolctl import threadpool_limits

    grouped = trainer.grouped_by_run(records)
    rows_by_key: dict[str, list[dict[str, Any]]] = {
        key: [] for keys in modes_to_keys.values() for key in keys
    }
    with threadpool_limits(limits=1):
        for test in runs:
            test_key = trainer.run_id(test)
            train_records = [record for record in records if record["run_path"] != test_key]
            if signature.scope == "same_type":
                same_type = [
                    record
                    for record in train_records
                    if record["titration_type"] == test.titration_type
                ]
                if len({record["run_path"] for record in same_type}) >= 2:
                    train_records = same_type
            test_records = grouped[test_key]
            x_train, x_test, _ = trainer.vectorize(
                [record["features"] for record in train_records],
                [record["features"] for record in test_records],
            )
            y_train = np.asarray(
                [
                    abs(float(record["current_volume_ml"]) - float(record["actual_ml"]))
                    <= signature.window_ml
                    for record in train_records
                ],
                dtype=int,
            )
            if len(set(y_train.tolist())) < 2:
                raise ValueError(f"{signature}: training fold contains one class")
            fitted = _bounded_model(signature.model_name, len(records))
            fitted.fit(x_train, y_train)
            if hasattr(fitted, "predict_proba"):
                probability = np.asarray(fitted.predict_proba(x_test), dtype=float)
                positive_index = list(fitted.classes_).index(1)
                scores = probability[:, positive_index]
            else:
                raw = np.asarray(fitted.decision_function(x_test), dtype=float)
                scores = 1.0 / (1.0 + np.exp(-raw))
            current = np.asarray(
                [float(record["current_volume_ml"]) for record in test_records],
                dtype=float,
            )
            aggregated = trainer.classifier_aggregate_predictions(current, scores)
            for mode, method_keys in modes_to_keys.items():
                predicted = aggregated[mode]
                for method_key in method_keys:
                    prediction = trainer.Prediction(
                        run_path=test_key,
                        titration_type=test.titration_type,
                        concentration_m=test.concentration_m,
                        actual_ml=test.theoretical_equivalence_volume_ml,
                        predicted_ml=predicted,
                        method="frame_zone_classifier",
                        model=signature.model_name,
                        fold=(
                            f"loo_{signature.scope}/"
                            f"window{signature.window_ml}_{mode}"
                        ),
                    )
                    rows_by_key[method_key].append(
                        trainer.row_from_prediction(prediction)
                        | {"method_key": method_key}
                    )
    return [row for key in sorted(rows_by_key) for row in rows_by_key[key]]


def evaluate_candidate_registry(
    runs: Sequence[CsvRun],
    records: Sequence[Mapping[str, Any]],
    registry: Mapping[CandidateSignature, Mapping[str, Sequence[str]]],
    *,
    max_workers: int,
) -> list[dict[str, Any]]:
    if max_workers < 1 or max_workers > 2:
        raise ValueError("max_workers must be 1 or 2")
    all_rows: list[dict[str, Any]] = []
    signatures = sorted(registry)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _evaluate_signature,
                signature,
                registry[signature],
                runs,
                records,
            ): signature
            for signature in signatures
        }
        for future in as_completed(futures):
            all_rows.extend(future.result())
    return sorted(
        all_rows,
        key=lambda row: (str(row["method_key"]), str(row["run_path"])),
    )


def select_typewise(all_prediction_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    copied = [dict(row) for row in all_prediction_rows]
    result = trainer.add_typewise_development_selector(copied)
    if result is None:
        raise RuntimeError("typewise development selection produced no result")
    return result


def _selected_method_rows(
    all_rows: Sequence[Mapping[str, Any]],
    selection: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for titration_type, detail in selection.items():
        method_key = str(detail["selected_method_key"])
        selected.extend(
            dict(row)
            for row in all_rows
            if row.get("method_key") == method_key
            and row.get("titration_type") == titration_type
        )
    return selected


def _typewise_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, float]]:
    predictions = [trainer._prediction_from_row(row) for row in rows]
    return trainer.typewise_metrics(predictions)


def _reference_summary(reference_dir: str | Path) -> dict[str, Any]:
    return json.loads(
        (Path(reference_dir) / "summary.json").read_text(encoding="utf-8")
    )


def verify_fusion_reference(
    runs: Sequence[CsvRun],
    records: Sequence[Mapping[str, Any]],
    registry: Mapping[CandidateSignature, Mapping[str, Sequence[str]]],
    *,
    reference_dir: str | Path,
    tolerance_ml: float = 1e-6,
) -> dict[str, Any]:
    """Recompute the four locked source methods and compare selected rows."""

    reference = _reference_summary(reference_dir)
    selector = reference["typewise_development_selector"]
    selection = selector["selection"]
    signatures: set[CandidateSignature] = set()
    for detail in selection.values():
        signature, _mode = parse_candidate_key(str(detail["selected_method_key"]))
        signatures.add(signature)
    subset_registry = {signature: registry[signature] for signature in signatures}
    recomputed = evaluate_candidate_registry(
        runs, records, subset_registry, max_workers=2
    )
    differences: list[dict[str, Any]] = []
    reference_rows = selector["prediction_rows"]
    for reference_row in reference_rows:
        titration_type = str(reference_row["titration_type"])
        method_key = str(selection[titration_type]["selected_method_key"])
        match = next(
            row
            for row in recomputed
            if row["method_key"] == method_key
            and row["run_path"] == reference_row["run_path"]
        )
        difference = abs(
            float(match["predicted_equivalence_volume_ml"])
            - float(reference_row["predicted_equivalence_volume_ml"])
        )
        differences.append(
            {
                "run_path": reference_row["run_path"],
                "method_key": method_key,
                "absolute_prediction_difference_ml": round(difference, 9),
            }
        )
    max_difference = max(
        item["absolute_prediction_difference_ml"] for item in differences
    )
    if max_difference > tolerance_ml:
        raise AssertionError(
            f"fusion reference pipeline mismatch: max difference={max_difference}"
        )
    metrics = selector["comparison_row"]
    if float(metrics["mape_percent"]) != 1.271147:
        raise AssertionError("locked fusion MAPE is not 1.271147")
    return {
        "passed": True,
        "max_absolute_prediction_difference_ml": max_difference,
        "checked_run_count": len(differences),
        "details": differences,
    }


def _group_result(
    group: str,
    columns: Sequence[str],
    selector: Mapping[str, Any],
    all_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    selected_rows = _selected_method_rows(all_rows, selector["selection"])
    metrics = trainer.metrics_for_predictions(
        [trainer._prediction_from_row(row) for row in selected_rows]
    )
    return {
        "feature_columns": list(columns),
        "feature_count": len(columns),
        "forbidden_features": [
            column for column in columns if trainer.is_forbidden_column(column)
        ],
        "metrics": metrics,
        "typewise_metrics": _typewise_metrics(selected_rows),
        "selection": selector["selection"],
        "selected_method_counts": dict(
            Counter(
                detail["selected_method_key"]
                for detail in selector["selection"].values()
            )
        ),
        "selected_predictions": selected_rows,
        "candidate_prediction_row_count": len(all_rows),
    }


def render_report(summary: Mapping[str, Any], command: str) -> str:
    labels = {
        "color_only": "색상 특징",
        "thermal_only": "열화상 특징",
        "color_thermal_fusion": "색상+열화상 특징",
    }
    sensor_only = not summary["feature_policy"]["current_volume_as_model_feature"]
    method_note = (
        "현재 주입량은 모델 입력에서 제외하고, 당량점 부근 label 생성과 "
        "프레임 점수의 최종 부피 집계에만 사용했다."
        if sensor_only
        else "현재 주입량을 모든 입력군의 공통 모델 특징으로 사용했다."
    )
    lines = [
        "# 보고서용 센서 입력군 개발 비교",
        "",
        "기존 `current_volume_no_progress`와 같은 12-run LORO 후보 및 적정 종류별 "
        "사후 개발 선택 절차를 사용했다. 독립 검증 또는 nested 검증 결과가 아니다.",
        "",
        method_note,
        "",
        "## 실행 명령",
        "",
        "```bash",
        command,
        "```",
        "",
        "## 전체 결과",
        "",
        "| 입력군 | MAE (mL) | RMSE (mL) | MAPE (%) |",
        "|---|---:|---:|---:|",
    ]
    for group in GROUPS:
        if group not in summary["groups"]:
            continue
        metrics = summary["groups"][group]["metrics"]
        lines.append(
            f"| {labels[group]} | {metrics['mae_ml']:.6f} | "
            f"{metrics['rmse_ml']:.6f} | {metrics['mape_percent']:.6f} |"
        )
    for group in GROUPS:
        if group not in summary["groups"]:
            continue
        result = summary["groups"][group]
        lines.extend(
            [
                "",
                f"## {labels[group]} 적정 종류별 결과",
                "",
                "| 적정 종류 | MAE (mL) | RMSE (mL) | MAPE (%) | 선택 방법 |",
                "|---|---:|---:|---:|---|",
            ]
        )
        for titration_type, metrics in result["typewise_metrics"].items():
            method = result["selection"][titration_type]["selected_method_key"]
            lines.append(
                f"| {titration_type} | {metrics['mae_ml']:.6f} | "
                f"{metrics['rmse_ml']:.6f} | {metrics['mape_percent']:.6f} | "
                f"`{method}` |"
            )
    limits = summary["resource_limits"]
    usage = summary["resource_usage"]
    lines.extend(
        [
            "",
            "## 감사 및 자원",
            "",
            (
                f"- 융합 12-run 재계산 최대 차이: "
                f"{summary['fusion_reference_check']['max_absolute_prediction_difference_ml']} mL"
                if summary["fusion_reference_check"] is not None
                else "- 기존 1.271147% 융합 기준은 현재 주입량을 모델 특징으로 사용하므로 "
                "센서-only 재계산의 기준값으로 사용하지 않았다."
            ),
            "- 명목 농도·이론 당량점·진행률·종료 정보는 feature에서 제외했다.",
            "- 센서 외 역사적 공통 통제 열은 세 군에서 동일하게 유지했다.",
            f"- 후보: {summary['candidate_registry']['frame_zone_method_count']}개 방법, "
            f"{summary['candidate_registry']['fit_signature_count']}개 fit signature.",
            f"- 역사적 전체 {summary['candidate_registry']['historical_all_method_count']}개 중 "
            f"비-frame/non-modality-pure 방법 "
            f"{summary['candidate_registry']['excluded_non_frame_method_count']}개는 제외했다.",
            f"- 자원 제한: max_workers={limits['max_workers']}, "
            f"model n_jobs={limits['model_n_jobs']}.",
            f"- 도구 내부 실행시간: {usage['evaluation_seconds']:.3f}초; "
            f"최대 RSS: {usage['max_rss_kb']} kB.",
            "",
        ]
    )
    return "\n".join(lines)


def evaluate(
    input_dir: str | Path,
    reference_dir: str | Path,
    output_dir: str | Path,
    *,
    grid_ml: float = 0.25,
    max_workers: int = 2,
    groups: Sequence[str] = GROUPS,
    include_current_volume_feature: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    unknown = sorted(set(groups) - set(GROUPS))
    if unknown:
        raise ValueError(f"unknown groups: {unknown}")
    runs = load_runs(input_dir)
    if len(runs) != 12:
        raise ValueError(f"historical comparison requires 12 runs, got {len(runs)}")
    reference_columns = load_reference_feature_columns(reference_dir)
    registry = load_candidate_registry(reference_dir)
    reference = _reference_summary(reference_dir)
    reference_prediction_rows = _load_csv(
        Path(reference_dir) / "all_predictions_merged.csv"
    )
    historical_method_keys = {
        str(row.get("method_key") or "")
        for row in reference_prediction_rows
        if row.get("method_key")
        and not str(row.get("method_key")).startswith(
            "typewise_development_selector:"
        )
    }
    frame_method_count = sum(
        len(keys)
        for modes in registry.values()
        for keys in modes.values()
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "schema_version": "report_modality_development_selector_v1",
        "analysis_type": "post_hoc_typewise_development_selection_not_nested_validation",
        "input_dir": str(input_dir),
        "reference_dir": str(reference_dir),
        "run_count": len(runs),
        "volume_grid_ml": grid_ml,
        "groups": {},
        "candidate_registry": {
            "source": str(Path(reference_dir) / "all_predictions_merged.csv"),
            "historical_all_method_count": len(historical_method_keys),
            "frame_zone_method_count": frame_method_count,
            "excluded_non_frame_method_count": len(historical_method_keys) - frame_method_count,
            "exclusion_reason": (
                "The 61 candidate-error, remaining-regression, and run-summary "
                "methods are not the frame-zone model/hyperparameter/aggregation "
                "family that produced the locked 1.27% selections and do not share "
                "one modality-pure frame-feature contract."
            ),
            "fit_signature_count": len(registry),
            "model_families": sorted(
                {signature.model_name for signature in registry}
            ),
            "zone_windows_ml": sorted(
                {signature.window_ml for signature in registry}
            ),
            "scopes": sorted({signature.scope for signature in registry}),
        },
        "feature_policy": {
            "ablation": "remove only the opposite sensor modality",
            "shared_controls_held_constant": [
                column
                for column in shared_control_columns(reference_columns)
                if include_current_volume_feature
                or column != "injected_volume_ml"
            ],
            "current_volume_as_model_feature": include_current_volume_feature,
            "current_volume_usage": (
                "model_feature_plus_label_and_final_volume_aggregation"
                if include_current_volume_feature
                else "label_and_final_volume_aggregation_only"
            ),
            "sample_concentration_as_feature": False,
            "theoretical_equivalence_as_feature": False,
            "progress_or_end_information_as_feature": False,
            "forbidden_features": sorted(trainer.FORBIDDEN_EXACT),
        },
        "selection_caveat": (
            "Each titration type selects its best method on the same three labeled "
            "development runs. This mirrors the historical development-selection "
            "procedure but is not nested or independent validation."
        ),
        "resource_limits": {"max_workers": max_workers, "model_n_jobs": 1},
    }
    summary["fusion_reference_check"] = None
    if include_current_volume_feature:
        fusion_columns = select_group_columns(
            reference_columns,
            "color_thermal_fusion",
            include_current_volume_feature=True,
        )
        fusion_records = build_group_records(
            runs,
            fusion_columns,
            grid_ml=grid_ml,
        )
        summary["fusion_reference_check"] = verify_fusion_reference(
            runs,
            fusion_records,
            registry,
            reference_dir=reference_dir,
        )
    if include_current_volume_feature and "color_thermal_fusion" in groups:
        fusion_selector = reference["typewise_development_selector"]
        fusion_rows = [
            dict(row)
            for row in fusion_selector["prediction_rows"]
        ]
        summary["groups"]["color_thermal_fusion"] = {
            "feature_columns": fusion_columns,
            "feature_count": len(fusion_columns),
            "forbidden_features": [
                column
                for column in fusion_columns
                if trainer.is_forbidden_column(column)
            ],
            "metrics": reference["best"]["metrics"],
            "typewise_metrics": reference["best"]["typewise_metrics"],
            "selection": fusion_selector["selection"],
            "selected_method_counts": dict(
                Counter(
                    detail["selected_method_key"]
                    for detail in fusion_selector["selection"].values()
                )
            ),
            "selected_predictions": fusion_rows,
            "candidate_prediction_row_count": 12 * summary["candidate_registry"]["frame_zone_method_count"],
            "locked_reference_mape_percent": 1.271147,
        }
        _write_csv(output / "selected_predictions_color_thermal_fusion.csv", fusion_rows)
        _write_csv(
            output / "typewise_selection_color_thermal_fusion.csv",
            [
                {"titration_type": titration_type, **detail}
                for titration_type, detail in fusion_selector["selection"].items()
            ],
        )
    evaluated_groups = (
        ("color_only", "thermal_only")
        if include_current_volume_feature
        else GROUPS
    )
    for group in evaluated_groups:
        if group not in groups:
            continue
        columns = select_group_columns(
            reference_columns,
            group,
            include_current_volume_feature=include_current_volume_feature,
        )
        records = build_group_records(runs, columns, grid_ml=grid_ml)
        all_rows = evaluate_candidate_registry(
            runs,
            records,
            registry,
            max_workers=max_workers,
        )
        selector = select_typewise(all_rows)
        result = _group_result(group, columns, selector, all_rows)
        summary["groups"][group] = result
        _write_csv(output / f"selected_predictions_{group}.csv", result["selected_predictions"])
        _write_csv(
            output / f"typewise_selection_{group}.csv",
            [
                {"titration_type": titration_type, **detail}
                for titration_type, detail in selector["selection"].items()
            ],
        )
    comparison_rows = []
    for group in GROUPS:
        if group not in summary["groups"]:
            continue
        metrics = summary["groups"][group]["metrics"]
        comparison_rows.append(
            {
                "group": group,
                "mae_ml": metrics["mae_ml"],
                "rmse_ml": metrics["rmse_ml"],
                "mape_percent": metrics["mape_percent"],
                "within_1pct_rate": metrics["within_1pct_rate"],
                "within_2pct_rate": metrics["within_2pct_rate"],
                "within_5pct_rate": metrics["within_5pct_rate"],
            }
        )
    summary["resource_usage"] = {
        "evaluation_seconds": round(time.perf_counter() - started, 6),
        "max_rss_kb": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
    }
    try:
        import sklearn

        sklearn_version = sklearn.__version__
    except Exception:
        sklearn_version = None
    summary["versions"] = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scikit_learn": sklearn_version,
    }
    _write_csv(output / "overall_comparison.csv", comparison_rows)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    command_parts = [
        "python3 tools/report_modality_development_selector.py "
        f"--input-dir {json.dumps(str(input_dir), ensure_ascii=False)} "
        f"--reference-dir {reference_dir} --output-dir {output_dir} "
        f"--volume-grid-ml {grid_ml} --max-workers {max_workers}"
    ]
    if not include_current_volume_feature:
        command_parts.append("--exclude-current-volume-feature")
    command_parts.extend(["--groups", *groups])
    command = " ".join(command_parts)
    (output / "report.md").write_text(
        render_report(summary, command),
        encoding="utf-8",
    )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--reference-dir", default=str(DEFAULT_REFERENCE_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--volume-grid-ml", type=float, default=0.25)
    parser.add_argument("--max-workers", type=int, choices=(1, 2), default=2)
    parser.add_argument(
        "--exclude-current-volume-feature",
        action="store_true",
        help=(
            "Exclude injected_volume_ml from model X while retaining it for "
            "zone labels and final predicted-volume aggregation."
        ),
    )
    parser.add_argument(
        "--groups",
        nargs="+",
        choices=GROUPS,
        default=list(GROUPS),
    )
    args = parser.parse_args(argv)
    summary = evaluate(
        args.input_dir,
        args.reference_dir,
        args.output_dir,
        grid_ml=args.volume_grid_ml,
        max_workers=args.max_workers,
        groups=args.groups,
        include_current_volume_feature=not args.exclude_current_volume_feature,
    )
    print(
        json.dumps(
            {
                group: {
                    "metrics": result["metrics"],
                    "selection": result["selection"],
                }
                for group, result in summary["groups"].items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
