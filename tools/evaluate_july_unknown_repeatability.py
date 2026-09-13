#!/usr/bin/env python3
"""Evaluate repeatability on three participant-designated July unknown-sample runs.

The actual concentration was not independently standardized, so this script
reports consistency statistics only. It must not emit accuracy/error metrics.
The endpoint model is frozen from the June 12-run development set.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
import tempfile
import zipfile
from dataclasses import asdict
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.ml_typewise_eval import load_runs
from tools.make_type_conditioned_ml_figures import ACCENT, INK, setup_style, style_axis
from tools.sensor_transition_candidate_union import generate_union_candidates
from tools.type_conditioned_sensor_sequence_search import TYPE_CONFIGS, select_frame


DEFAULT_ARCHIVE = ROOT / "Downloads.zip"
DEFAULT_TRAINING_DIR = ROOT / "머신러닝용 파일모음"
DEFAULT_OUTPUT_DIR = ROOT / "data/analysis/july_unknown_repeatability"

SELECTED_RUNS = (
    "auto-titration-live-20260726-150424-session-5.csv",
    "auto-titration-live-20260726-151233-session-7.csv",
    "auto-titration-live-20260726-151632-session-8.csv",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def make_figure(rows: list[dict], summary: dict, path: Path) -> None:
    setup_style()
    x = [1, 2, 3]
    values = [row["frozen_model_predicted_concentration_M"] for row in rows]
    mean = summary["frozen_model_repeatability"]["mean_M"]

    fig, ax = plt.subplots(figsize=(9.2, 5.6))
    ax.plot(
        x,
        values,
        color=ACCENT,
        linewidth=2.4,
        marker="o",
        markersize=9,
        markeredgecolor="white",
        markeredgewidth=1.2,
    )
    ax.axhline(
        mean,
        color=INK,
        linewidth=1.6,
        linestyle="--",
        label=f"평균 {mean:.5f} M",
    )
    ax.set_title("동일 미지 시료의 반복 측정", loc="left", fontweight="bold", pad=14)
    ax.set_xlabel("반복 측정")
    ax.set_ylabel("모델 예측 농도 (M)")
    ax.set_xticks(x, ["1회", "2회", "3회"])
    padding = max(0.0015, (max(values) - min(values)) * 0.9)
    ax.set_ylim(min(values) - padding, max(values) + padding)
    style_axis(ax)
    ax.legend(loc="lower right", frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def evaluate(archive: Path, training_dir: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    training_runs = load_runs(training_dir)
    if len(training_runs) != 12:
        raise AssertionError(f"expected 12 frozen development runs, got {len(training_runs)}")
    training_sets = {
        str(run.path): generate_union_candidates(run.rows) for run in training_runs
    }

    with tempfile.TemporaryDirectory(prefix="july_unknown_repeatability_") as temp:
        with zipfile.ZipFile(archive) as handle:
            handle.extractall(temp)
        available = {run.path.name: run for run in load_runs(temp)}
        missing = sorted(set(SELECTED_RUNS) - set(available))
        if missing:
            raise FileNotFoundError(f"selected July runs are missing: {missing}")

        rows = []
        selected_hashes = {}
        for repeat_index, name in enumerate(SELECTED_RUNS, start=1):
            test = available[name]
            if test.titration_type != "strong_acid_strong_base":
                raise AssertionError(f"unexpected titration type in {name}: {test.titration_type}")
            candidate_sets = dict(training_sets)
            candidates = generate_union_candidates(test.rows)
            candidate_sets[str(test.path)] = candidates
            config = TYPE_CONFIGS[test.titration_type]
            frame, confirmation, margin, global_paths, type_paths = select_frame(
                training_runs, test, candidate_sets, config
            )
            predicted_volume = float(test.rows[frame]["injected_volume_ml"])
            sample_volume = float(test.rows[0]["sample_volume_ml"])
            titrant_concentration = float(test.rows[0]["titrant_concentration_M"])
            predicted_concentration = (
                titrant_concentration * predicted_volume / sample_volume
            )
            old_prediction_text = next(
                (
                    row.get("sample_concentration_from_predicted_equivalence_M", "").strip()
                    for row in test.rows
                    if row.get("sample_concentration_from_predicted_equivalence_M", "").strip()
                ),
                "",
            )
            if not old_prediction_text:
                raise ValueError(f"recorded model prediction is missing from {name}")
            old_prediction = float(old_prediction_text)
            selected_hashes[name] = sha256(test.path)
            rows.append(
                {
                    "repeat_index": repeat_index,
                    "source_file": name,
                    "row_count": len(test.rows),
                    "titration_type": test.titration_type,
                    "participant_scope": "same_unknown_solution_repeatability",
                    "actual_concentration_M": "unknown_not_standardized",
                    "recorded_nominal_concentration_M_audit_only": test.rows[0].get(
                        "sample_concentration_M", ""
                    ),
                    "recorded_old_model_prediction_M": old_prediction,
                    "frozen_model_selected_frame": frame,
                    "frozen_model_confirmation_frame": confirmation,
                    "frozen_model_score_margin": margin,
                    "frozen_model_predicted_endpoint_ml": predicted_volume,
                    "frozen_model_predicted_concentration_M": predicted_concentration,
                    "candidate_count": len(candidates),
                    "frozen_training_run_count": len(global_paths),
                    "type_training_run_count": len(type_paths),
                }
            )

    new_values = [row["frozen_model_predicted_concentration_M"] for row in rows]
    old_values = [row["recorded_old_model_prediction_M"] for row in rows]

    def repeatability(values: list[float]) -> dict:
        mean = statistics.mean(values)
        sample_sd = statistics.stdev(values)
        return {
            "n": len(values),
            "mean_M": mean,
            "sample_sd_M": sample_sd,
            "cv_percent": sample_sd / mean * 100.0,
            "min_M": min(values),
            "max_M": max(values),
            "range_M": max(values) - min(values),
        }

    new_repeatability = repeatability(new_values)
    old_repeatability = repeatability(old_values)
    summary = {
        "schema_version": "july_unknown_repeatability_v1",
        "claim_scope": (
            "repeatability_only_for_three_participant_designated_runs_of_the_same_unknown_solution; "
            "actual_concentration_not_standardized; no accuracy_or_error_claim"
        ),
        "selection_note": (
            "Sessions 5, 7 and 8 were designated by the participant as the usable same-solution "
            "repeatability set. Other July files are excluded from this analysis."
        ),
        "model_note": (
            "The type-conditioned sensor endpoint model and aggregation settings are frozen from "
            "the June 12-run development set. All 12 June runs are used for fitting before applying "
            "the model to each later July run."
        ),
        "accuracy_metrics_computed": False,
        "accuracy_metrics_reason": "actual concentration was not independently standardized",
        "frozen_model_repeatability": new_repeatability,
        "recorded_old_model_repeatability": old_repeatability,
        "cv_ratio_new_to_old": (
            new_repeatability["cv_percent"] / old_repeatability["cv_percent"]
        ),
        "rows": rows,
        "model_config": asdict(TYPE_CONFIGS["strong_acid_strong_base"]),
        "provenance": {
            "archive_sha256": sha256(archive),
            "selected_csv_sha256": selected_hashes,
            "training_csv_sha256": {
                run.path.name: sha256(run.path)
                for run in sorted(training_runs, key=lambda item: item.path.name)
            },
            "script_sha256": {
                "tools/evaluate_july_unknown_repeatability.py": sha256(Path(__file__)),
                "tools/type_conditioned_sensor_sequence_search.py": sha256(
                    ROOT / "tools/type_conditioned_sensor_sequence_search.py"
                ),
                "tools/sensor_transition_candidate_union.py": sha256(
                    ROOT / "tools/sensor_transition_candidate_union.py"
                ),
            },
        },
    }

    write_csv(output_dir / "july_unknown_repeatability_predictions.csv", rows)
    (output_dir / "july_unknown_repeatability_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    insert = f"""# 보고서 삽입 문안: 미지 시료 반복 측정

농도를 별도로 표정하지 않은 동일한 미지 시료를 세 차례 반복 측정하였다. 고정한 적정 종류 조건부 센서 모델이 예측한 농도는 {new_values[0]:.5f} M, {new_values[1]:.5f} M, {new_values[2]:.5f} M였다. 평균은 {new_repeatability['mean_M']:.5f} M, 표본 표준편차는 {new_repeatability['sample_sd_M']:.6f} M, 변동계수는 {new_repeatability['cv_percent']:.2f}%였다. 실제 농도를 별도로 표정하지 않았으므로 정확도나 오차율은 계산하지 않고, 동일 시료에 대한 반복 측정값의 일관성만 평가하였다.

**그림 캡션.** 농도를 별도로 표정하지 않은 동일 미지 시료의 3회 반복 측정 결과. 점선은 세 예측값의 평균을 나타낸다. 실제 농도가 확인되지 않았으므로 정확도 비교가 아니라 반복성만 제시하였다.

## 사용 금지 표현

- 실제 농도는 0.100 M였다.
- 독립 검증 오차율은 0.96%였다.
- 모델의 정확도는 99.04%였다.

`0.96%`는 정확도나 오차율이 아니라 세 예측값의 **변동계수**이다.
"""
    (output_dir / "보고서_삽입문안_미지시료_반복성.md").write_text(
        insert, encoding="utf-8"
    )
    make_figure(
        rows,
        summary,
        output_dir / "미지시료_3회_반복측정_CV.png",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--training-dir", type=Path, default=DEFAULT_TRAINING_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    summary = evaluate(args.archive, args.training_dir, args.output_dir)
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "mean_M": summary["frozen_model_repeatability"]["mean_M"],
                "sample_sd_M": summary["frozen_model_repeatability"]["sample_sd_M"],
                "cv_percent": summary["frozen_model_repeatability"]["cv_percent"],
                "accuracy_metrics_computed": summary["accuracy_metrics_computed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
