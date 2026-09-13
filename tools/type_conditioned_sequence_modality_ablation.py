#!/usr/bin/env python3
"""Fixed-architecture sensor-modality ablation for the latest sequence ranker.

The fused type-conditioned configuration is held fixed while candidate
generation and candidate features are restricted to color-only, thermal-only,
or color+thermal.  This isolates input removal; it is not a new independent
validation and it does not retune the fixed fusion-selected configuration for
each single-sensor input.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.ml_typewise_eval import CsvRun, load_runs  # noqa: E402
from tools import sensor_sequence_endpoint_search as metrics_base  # noqa: E402
from tools import sensor_transition_candidate_union as candidate_union  # noqa: E402
from tools import type_conditioned_sensor_sequence_search as latest  # noqa: E402

DEFAULT_INPUT_DIR = Path("머신러닝용 파일모음")
DEFAULT_OUTPUT_DIR = Path("data/ml/type_conditioned_sequence_modality_ablation")
MODALITIES = ("color", "thermal", "fusion")


def allowed_feature_indices(modality: str) -> tuple[int, ...]:
    names = candidate_union.feature_names()
    if modality == "fusion":
        return tuple(range(len(names)))
    if modality == "color":
        return tuple(
            index
            for index, name in enumerate(names)
            if name.startswith("color_") or name == "candidate_consensus"
        )
    if modality == "thermal":
        return tuple(
            index
            for index, name in enumerate(names)
            if name.startswith("thermal_") or name == "candidate_consensus"
        )
    raise ValueError(f"unknown modality: {modality}")


def _active_sources(modality: str) -> tuple[str, ...]:
    if modality == "fusion":
        return candidate_union.MODALITIES
    if modality in {"color", "thermal"}:
        return (modality,)
    raise ValueError(f"unknown modality: {modality}")


def generate_candidates(
    rows: Sequence[Mapping[str, Any]], modality: str,
) -> list[candidate_union.Candidate]:
    """Generate a candidate union that cannot use the excluded sensor."""

    matrix, thermal_valid = candidate_union.sensor_matrix(rows)
    evidence: dict[int, list[tuple[int, float, str]]] = defaultdict(list)
    for baseline, window, threshold, confirmation, refractory, source_modality in itertools.product(
        candidate_union.BASELINES,
        candidate_union.WINDOWS,
        candidate_union.THRESHOLDS,
        candidate_union.CONFIRMATIONS,
        candidate_union.REFRACTORIES,
        _active_sources(modality),
    ):
        if baseline + 2 * window + confirmation >= len(matrix):
            continue
        source = (
            f"{source_modality}:b{baseline}:w{window}:t{threshold}:"
            f"c{confirmation}:r{refractory}"
        )
        detected = candidate_union.detect_one(
            matrix,
            thermal_valid,
            baseline=baseline,
            window=window,
            threshold=threshold,
            confirmation=confirmation,
            refractory=refractory,
            modality=source_modality,
        )
        for boundary, confirmed, strength in detected:
            evidence[boundary].append((confirmed, strength, source))

    if len(evidence) > candidate_union.MAX_CANDIDATES:
        ordered = sorted(
            evidence,
            key=lambda boundary: (
                -len(evidence[boundary]),
                -sum(item[1] for item in evidence[boundary]),
                boundary,
            ),
        )[:candidate_union.MAX_CANDIDATES]
        evidence = {boundary: evidence[boundary] for boundary in ordered}

    allowed = set(allowed_feature_indices(modality))
    output: list[candidate_union.Candidate] = []
    for boundary in sorted(evidence):
        items = evidence[boundary]
        source_counts = Counter(item[2].split(":", 1)[0] for item in items)
        full_features = candidate_union.local_sensor_features(
            matrix,
            thermal_valid,
            boundary,
            len(items),
            source_counts,
        )
        features = tuple(
            value if index in allowed else 0.0
            for index, value in enumerate(full_features)
        )
        output.append(candidate_union.Candidate(
            boundary=boundary,
            confirmation=min(item[0] for item in items),
            features=features,
            support=len(items),
            sources=tuple(sorted(item[2] for item in items)),
        ))
    return output


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    columns = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def evaluate_modality(
    runs: Sequence[CsvRun], modality: str, *, output_dir: Path,
) -> dict[str, Any]:
    if len(runs) != 12:
        raise ValueError(f"expected exactly 12 runs, found {len(runs)}")
    candidate_sets = {
        str(run.path): generate_candidates(run.rows, modality) for run in runs
    }
    empty = [Path(path).name for path, values in candidate_sets.items() if not values]
    if empty:
        raise ValueError(f"{modality} produced no candidates for: {empty}")
    if modality == "fusion":
        expected = {
            str(run.path): candidate_union.generate_union_candidates(run.rows)
            for run in runs
        }
        if candidate_sets != expected:
            raise AssertionError("fusion ablation candidate generation changed")

    predictions: list[dict[str, Any]] = []
    for test_run in runs:
        outer_train = [run for run in runs if run.path != test_run.path]
        config = latest.TYPE_CONFIGS[test_run.titration_type]
        frame, confirmation, margin, global_paths, type_paths = latest.select_frame(
            outer_train,
            test_run,
            candidate_sets,
            config,
        )
        predicted = float(test_run.rows[frame]["injected_volume_ml"])
        actual = float(test_run.theoretical_equivalence_volume_ml)
        error = predicted - actual
        predictions.append({
            "modality": modality,
            "run_path": str(test_run.path),
            "titration_type": test_run.titration_type,
            "actual_equivalence_volume_ml": actual,
            "predicted_equivalence_volume_ml": predicted,
            "signed_error_ml": error,
            "absolute_error_ml": abs(error),
            "absolute_error_percent": abs(error) / actual * 100.0,
            "selected_frame_audit_only": frame,
            "candidate_count": len(candidate_sets[str(test_run.path)]),
            "confirmation_frame_audit_only": confirmation,
            "top_two_score_margin_audit_only": margin,
            "global_model_run_paths": json.dumps(global_paths, ensure_ascii=False),
            "type_model_run_paths": json.dumps(type_paths, ensure_ascii=False),
        })

    metrics = metrics_base._metrics(predictions)
    type_metrics = []
    for titration_type in sorted({run.titration_type for run in runs}):
        selected = [
            row for row in predictions if row["titration_type"] == titration_type
        ]
        type_metrics.append({
            "modality": modality,
            "titration_type": titration_type,
            **metrics_base._metrics(selected),
        })

    names = candidate_union.feature_names()
    allowed = allowed_feature_indices(modality)
    summary = {
        "schema_version": "type_conditioned_sequence_fixed_config_modality_ablation_v1",
        "modality": modality,
        "claim_scope": (
            "same_12_run_fixed_fusion_selected_configuration_ablation; "
            "not modality_specific_retuning and not independent_external_validation"
        ),
        "architecture": "type_conditioned_sensor_union_dense_aggregation_ranker",
        "run_count": len(runs),
        "split": "outer_leave_one_run_out_for_ranker_fit",
        "known_context_inputs": ["titration_type"],
        "base_sensor_columns": (
            ["visible_H_mean", "visible_S_mean", "visible_V_mean"]
            if modality == "color"
            else ["thermal_raw_roi_p50", "thermal_raw_roi_p95"]
            if modality == "thermal"
            else [
                "visible_H_mean", "visible_S_mean", "visible_V_mean",
                "thermal_raw_roi_p50", "thermal_raw_roi_p95",
            ]
        ),
        "active_candidate_features": [names[index] for index in allowed],
        "excluded_candidate_features": [
            name for index, name in enumerate(names) if index not in set(allowed)
        ],
        "fixed_type_configs": {
            key: latest.asdict(value) for key, value in sorted(latest.TYPE_CONFIGS.items())
        },
        "metrics": metrics,
        "type_metrics": type_metrics,
        "predictions": predictions,
        "limitations": [
            "The type-specific configurations were selected using the fused development data.",
            "Single-modality configurations were not retuned, so this is an input-removal ablation.",
            "The same 12 development runs are used; this is not independent external validation.",
            "Each chemistry/concentration condition has one run.",
            "Theoretical endpoints provide training labels.",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "predictions.csv", predictions)
    _write_csv(output_dir / "type_metrics.csv", type_metrics)
    _write_csv(
        output_dir / "feature_manifest.csv",
        [{"modality": modality, "feature": names[index]} for index in allowed],
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def create_comparison_figure(rows: Sequence[Mapping[str, Any]], output: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/auto-titration-matplotlib")
    import matplotlib.pyplot as plt

    labels = ["Color", "Thermal", "Fusion"]
    colors = ["#3B82F6", "#F59E0B", "#10B981"]
    mape = [float(row["mape_percent"]) for row in rows]
    mape_sd = [float(row.get("mape_percent_sd", 0.0)) for row in rows]
    fig, axis = plt.subplots(figsize=(7.2, 4.2), constrained_layout=True)
    bars = axis.bar(
        labels,
        mape,
        color=colors,
        width=0.62,
        yerr=mape_sd if any(mape_sd) else None,
        capsize=5 if any(mape_sd) else 0,
    )
    axis.set_ylabel("MAPE (%)")
    upper = max(value + error for value, error in zip(mape, mape_sd))
    axis.set_ylim(0, upper * 1.22 if upper > 0 else 1)
    axis.grid(axis="y", alpha=0.22)
    axis.spines[["top", "right"]].set_visible(False)
    for bar, value, error in zip(bars, mape, mape_sd):
        axis.text(
            bar.get_x() + bar.get_width() / 2,
            value + error,
            f"{value:.2f}%",
            ha="center",
            va="bottom",
            fontsize=11,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=300, bbox_inches="tight")
    plt.close(fig)


def run_all(
    input_dir: str | Path = DEFAULT_INPUT_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    runs = load_runs(input_dir)
    root = Path(output_dir)
    summaries = [
        evaluate_modality(runs, modality, output_dir=root / modality)
        for modality in MODALITIES
    ]
    comparison = [
        {"modality": item["modality"], **item["metrics"]} for item in summaries
    ]
    _write_csv(root / "comparison.csv", comparison)
    create_comparison_figure(comparison, root / "modality_mape.png")
    combined = {
        "schema_version": "type_conditioned_sequence_fixed_config_modality_comparison_v1",
        "comparison": comparison,
        "interpretation_scope": (
            "fixed-configuration input-removal ablation; use the nested modality comparison "
            "for modality-specific model-selection performance"
        ),
    }
    (root / "comparison.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    by_modality = {row["modality"]: row for row in comparison}
    report = [
        "# 최신 시계열 고정구조 센서 ablation", "",
        "같은 적정 종류별 모델 구조와 설정을 유지한 채 입력 센서만 제거하여 비교하였다.",
        "이 값은 같은 12회 개발자료의 입력 제거 실험이며 독립 검증값은 아니다.", "",
        "| 입력 | MAE (mL) | RMSE (mL) | MAPE (%) |",
        "|---|---:|---:|---:|",
        (
            f"| 색상 | {by_modality['color']['mae_ml']:.3f} | "
            f"{by_modality['color']['rmse_ml']:.3f} | "
            f"{by_modality['color']['mape_percent']:.3f} |"
        ),
        (
            f"| 열화상 | {by_modality['thermal']['mae_ml']:.3f} | "
            f"{by_modality['thermal']['rmse_ml']:.3f} | "
            f"{by_modality['thermal']['mape_percent']:.3f} |"
        ),
        (
            f"| 색상+열화상 | {by_modality['fusion']['mae_ml']:.3f} | "
            f"{by_modality['fusion']['rmse_ml']:.3f} | "
            f"{by_modality['fusion']['mape_percent']:.3f} |"
        ),
        "",
        "융합 설정은 같은 개발자료에서 선택되었으므로, 이 표는 센서 제거에 따른 내부 성능 변화를 보여준다.",
        "센서별 모델 선택 성능은 별도의 중첩 검증 결과와 함께 해석해야 한다.",
    ]
    (root / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return combined


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    result = run_all(args.input_dir, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
