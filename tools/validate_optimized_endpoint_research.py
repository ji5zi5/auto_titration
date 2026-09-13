#!/usr/bin/env python3
"""Fail-closed professor/critic gate for endpoint-ml-maximize."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import pickle
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.ml_typewise_eval import load_runs  # noqa: E402
from auto_titrator.type_conditioned_sensor_live_model import (  # noqa: E402
    ARTIFACT_TYPE,
    load_type_conditioned_sensor_model,
    predict_type_conditioned_sensor_equivalence,
)
from tools import windows_live_collect  # noqa: E402
from tools.audit_july_endpoint_runs import build_inventory  # noqa: E402
from tools.export_type_conditioned_sensor_live_model import export_model  # noqa: E402


MODEL = ROOT / "data/labeled/type-conditioned-sensor-endpoint-ranker.pkl"
OLD_MODEL = ROOT / "data/labeled/typewise-current-volume-classifier.pkl"
JUNE = ROOT / "머신러닝용 파일모음"
JULY = ROOT / "Downloads.zip"
STRATEGY = ROOT / "data/labeled/type-conditioned-sensor-endpoint-strategy-research.json"
ROBUSTNESS = ROOT / "data/labeled/type-conditioned-sensor-endpoint-robustness.json"
PARTIAL = ROOT / "data/labeled/type-conditioned-partial-pooling-research.json"
INVENTORY = ROOT / "data/labeled/july-endpoint-run-inventory.json"
MODALITY_FIXED = ROOT / "data/ml/type_conditioned_sequence_modality_ablation/comparison.json"
MODALITY_NESTED = ROOT / "data/ml/latest_sequence_modality_nested_comparison/comparison.json"
SOURCE_SUMMARY = ROOT / "data/ml/type_conditioned_sensor_sequence_search/summary.json"
OUTPUT = ROOT / "data/labeled/type-conditioned-sensor-endpoint-optimized-validation.json"
SENSOR_KEYS = (
    "injected_volume_ml",
    "visible_H_mean",
    "visible_S_mean",
    "visible_V_mean",
    "thermal_raw_roi_p50",
    "thermal_raw_roi_p95",
)
SELECTED_JULY = {
    "auto-titration-live-20260726-150424-session-5.csv",
    "auto-titration-live-20260726-151233-session-7.csv",
    "auto-titration-live-20260726-151632-session-8.csv",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def densify(rows: Sequence[Mapping[str, Any]], factor: int = 6) -> list[dict[str, Any]]:
    output = []
    for before, after in zip(rows, rows[1:]):
        output.append(dict(before))
        for index in range(1, factor):
            weight = index / factor
            row = dict(before)
            for key in SENSOR_KEYS:
                try:
                    row[key] = (
                        float(before[key]) * (1.0 - weight)
                        + float(after[key]) * weight
                    )
                except (KeyError, TypeError, ValueError):
                    pass
            output.append(row)
    output.append(dict(rows[-1]))
    return output


def predict(artifact: Mapping[str, Any], run, rows=None) -> dict[str, Any]:
    return predict_type_conditioned_sensor_equivalence(
        artifact,
        run.rows if rows is None else rows,
        run.titration_type,
    )


def mape(pairs: Sequence[tuple[float, float]]) -> float:
    return statistics.mean(abs(predicted - actual) / actual * 100.0 for actual, predicted in pairs)


def exact_live_csv_buffer_prediction(artifact: Mapping[str, Any], run) -> dict[str, Any]:
    buffer = windows_live_collect.LiveCsvBuffer(
        output_path=ROOT / "data/raw/validator-endpoint.csv",
        endpoint_prediction_model=dict(artifact),
    )
    buffer.start_recording(
        experiment_metadata={"titration_type": run.titration_type}
    )
    rows = [dict(row) for row in run.rows]
    for row in rows:
        for key in (
            "predicted_equivalence_volume_ml",
            "predicted_equivalence_confidence",
            "predicted_equivalence_source",
            "predicted_equivalence_evidence",
            "predicted_equivalence_model_key",
        ):
            row.pop(key, None)
    with buffer._condition:
        buffer._rows = rows
        buffer._refresh_fieldnames_locked()
    return buffer.stop_recording()


def run_tests() -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "unittest",
        "tests.test_type_conditioned_sensor_live_model",
        "tests.test_typewise_live_model",
        "tests.test_windows_live_collect",
        "tests.test_website_assets",
        "tests.test_dashboard_server",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    combined = completed.stdout + completed.stderr
    count = None
    if "Ran " in combined:
        try:
            count = int(combined.rsplit("Ran ", 1)[1].split(" test", 1)[0])
        except (ValueError, IndexError):
            pass
    return {
        "command": command,
        "returncode": completed.returncode,
        "passed": completed.returncode == 0,
        "count": count,
        "failure_tail": "" if completed.returncode == 0 else combined[-6000:],
    }


def validate() -> dict[str, Any]:
    required = [
        MODEL,
        OLD_MODEL,
        STRATEGY,
        ROBUSTNESS,
        PARTIAL,
        INVENTORY,
        MODALITY_FIXED,
        MODALITY_NESTED,
        SOURCE_SUMMARY,
        JULY,
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        return {
            "status": "fail",
            "decision": "INSUFFICIENT_EVIDENCE",
            "missing": missing,
        }

    artifact = load_type_conditioned_sensor_model(MODEL)
    if artifact is None:
        raise AssertionError("model loader unexpectedly returned None")
    june_runs = load_runs(JUNE)
    expected_types = {
        "strong_acid_strong_base",
        "strong_acid_weak_base",
        "weak_acid_strong_base",
        "weak_acid_weak_base",
    }

    native_pairs = []
    dense_pairs = []
    dense_drifts = []
    baseline_predictions = {}
    dense_predictions = {}
    for run in june_runs:
        baseline = predict(artifact, run)
        dense = predict(artifact, run, densify(run.rows))
        actual = float(run.theoretical_equivalence_volume_ml)
        base_volume = float(baseline["predicted_equivalence_volume_ml"])
        dense_volume = float(dense["predicted_equivalence_volume_ml"])
        native_pairs.append((actual, base_volume))
        dense_pairs.append((actual, dense_volume))
        dense_drifts.append(abs(dense_volume - base_volume))
        baseline_predictions[run.path.name] = baseline
        dense_predictions[run.path.name] = dense

    metadata_invariant = True
    forbidden_metadata = (
        "sample_concentration_M",
        "theoretical_equivalence_volume_ml",
        "distance_to_equivalence_ml",
        "time_to_equivalence_s",
        "progress_fraction",
        "status_label",
        "actual_equivalence_volume_ml",
        "predicted_equivalence_volume_ml",
    )
    for run in june_runs:
        altered = [dict(row) for row in run.rows]
        for index, row in enumerate(altered):
            for offset, key in enumerate(forbidden_metadata, start=1):
                row[key] = 100000.0 + index * 17.0 + offset
        result = predict(artifact, run, altered)
        metadata_invariant &= (
            result["predicted_equivalence_volume_ml"]
            == baseline_predictions[run.path.name]["predicted_equivalence_volume_ml"]
        )

    dropout = {"visible": 0, "thermal": 0, "flat": 0}
    for run in june_runs:
        for modality, keys in {
            "visible": ("visible_H_mean", "visible_S_mean", "visible_V_mean"),
            "thermal": ("thermal_raw_roi_p50", "thermal_raw_roi_p95"),
        }.items():
            altered = [dict(row) for row in run.rows]
            for row in altered:
                for key in keys:
                    row[key] = ""
            try:
                predict(artifact, run, altered)
            except ValueError:
                dropout[modality] += 1
        flat = [dict(row) for row in run.rows]
        for row in flat:
            row.update(
                {
                    "visible_H_mean": 10.0,
                    "visible_S_mean": 0.5,
                    "visible_V_mean": 0.5,
                    "thermal_raw_roi_p50": 1000.0,
                    "thermal_raw_roi_p95": 1010.0,
                }
            )
        try:
            predict(artifact, run, flat)
        except ValueError:
            dropout["flat"] += 1

    exact_path_run = june_runs[0]
    exact_status = exact_live_csv_buffer_prediction(artifact, exact_path_run)
    exact_path_matches = math.isclose(
        float(exact_status["predicted_equivalence_volume_ml"]),
        float(
            baseline_predictions[exact_path_run.path.name][
                "predicted_equivalence_volume_ml"
            ]
        ),
        abs_tol=1e-9,
    ) and exact_status["predicted_equivalence_source"] == (
        "type_conditioned_sensor_endpoint_ranker"
    )

    july_inventory = build_inventory(JULY)
    inventory_file = json.loads(INVENTORY.read_text(encoding="utf-8"))
    inventory_reproducible = july_inventory == inventory_file
    july_cv = None
    july_rows = []
    with tempfile.TemporaryDirectory(prefix="optimized_endpoint_july_") as temp:
        import zipfile

        with zipfile.ZipFile(JULY) as archive:
            archive.extractall(temp)
        available = {run.path.name: run for run in load_runs(temp)}
        concentrations = []
        for name in sorted(SELECTED_JULY):
            run = available[name]
            result = predict(artifact, run)
            volume = float(result["predicted_equivalence_volume_ml"])
            concentration = (
                float(run.rows[0]["titrant_concentration_M"])
                * volume
                / float(run.rows[0]["sample_volume_ml"])
            )
            concentrations.append(concentration)
            july_rows.append(
                {"source_file": name, "endpoint_ml": volume, "concentration_M": concentration}
            )
        july_cv = statistics.stdev(concentrations) / statistics.mean(concentrations) * 100.0

    latency_samples = []
    dense_longest = densify(max(june_runs, key=lambda item: len(item.rows)).rows)
    latency_run = max(june_runs, key=lambda item: len(item.rows))
    predict(artifact, latency_run, dense_longest)
    for _ in range(5):
        started = time.perf_counter()
        predict(artifact, latency_run, dense_longest)
        latency_samples.append(time.perf_counter() - started)
    latency_p95 = sorted(latency_samples)[-1]

    strategy = json.loads(STRATEGY.read_text(encoding="utf-8"))
    partial = json.loads(PARTIAL.read_text(encoding="utf-8"))
    robustness = json.loads(ROBUSTNESS.read_text(encoding="utf-8"))
    modality_fixed = json.loads(MODALITY_FIXED.read_text(encoding="utf-8"))
    modality_nested = json.loads(MODALITY_NESTED.read_text(encoding="utf-8"))
    source = json.loads(SOURCE_SUMMARY.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="endpoint_reexport_") as temp:
        reproduced = Path(temp) / MODEL.name
        export_model(
            input_dir=JUNE,
            summary_path=SOURCE_SUMMARY,
            output_path=reproduced,
        )
        reproduced_artifact = load_type_conditioned_sensor_model(reproduced)
        if reproduced_artifact is None:
            raise AssertionError("reproduced artifact failed to load")
        deterministic_artifact = (
            reproduced_artifact.get("deployment_strategy")
            == artifact.get("deployment_strategy")
            and {
                key: value.get("config")
                for key, value in reproduced_artifact["models"].items()
            }
            == {
                key: value.get("config")
                for key, value in artifact["models"].items()
            }
            and all(
                predict(reproduced_artifact, run)["predicted_equivalence_volume_ml"]
                == baseline_predictions[run.path.name][
                    "predicted_equivalence_volume_ml"
                ]
                for run in june_runs
            )
        )

    tests = run_tests()
    tracked_paths = [
        MODEL,
        ROOT / "auto_titrator/type_conditioned_sensor_live_model.py",
        ROOT / "tools/export_type_conditioned_sensor_live_model.py",
        ROOT / "tools/windows_live_collect.py",
        ROOT / "launchers/windows/20_windows_live_collect.bat",
    ]
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", *[str(path.relative_to(ROOT)) for path in tracked_paths]],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).returncode == 0

    checks = {
        "artifact_schema": artifact.get("artifact_type") == ARTIFACT_TYPE,
        "four_routes": set(artifact.get("models") or {}) == expected_types,
        "incumbent_fold_median_strategy_retained": artifact.get("deployment_strategy")
        == "median_of_12_leave_one_run_out_rankers",
        "twelve_dispersion_folds_each": all(
            len(entry.get("fold_estimators") or []) == 12
            for entry in artifact["models"].values()
        ),
        "strategy_study_keeps_july_out_of_selection": strategy.get("july_usage")
        == "descriptive_repeatability_only_not_model_selection",
        "incumbent_replay_baseline_not_regressed": mape(native_pairs) <= 1.10561,
        "partial_pooling_challenger_rejected": float(partial["metrics"]["mape_percent"])
        > float(strategy["nested_run_level_metrics"]["single_full_fit"]["mape_percent"]),
        "metadata_invariance": metadata_invariant,
        "visible_dropout_abstains": dropout["visible"] == len(june_runs),
        "thermal_dropout_abstains": dropout["thermal"] == len(june_runs),
        "flat_signal_abstains": dropout["flat"] == len(june_runs),
        "dense_mean_drift_bounded": statistics.mean(dense_drifts) <= 0.30,
        "dense_max_drift_bounded": max(dense_drifts) <= 1.10,
        "dense_prediction_uses_volume_resampling": all(
            "volume_resampled" in row["predicted_equivalence_evidence"]
            for row in dense_predictions.values()
        ),
        "exact_windows_buffer_path": exact_path_matches,
        "july_inventory_all_runs": july_inventory["loadable_run_count"] == 11,
        "july_inventory_reproducible": inventory_reproducible,
        "july_not_accuracy_gate": july_inventory["accuracy_claim_allowed"] is False,
        "modality_fixed_comparison_present": {
            row["modality"] for row in modality_fixed["comparison"]
        }
        == {"color", "thermal", "fusion"},
        "modality_nested_comparison_present": {
            row["modality"] for row in modality_nested["comparison"]
        }
        == {"color", "thermal", "fusion"},
        "unvalidated_unimodal_routes_not_promoted": dropout["visible"]
        == dropout["thermal"]
        == len(june_runs),
        "latency_p95_under_2s": latency_p95 <= 2.0,
        "artifact_reexport_prediction_deterministic": deterministic_artifact,
        "rollback_artifact_present": OLD_MODEL.exists(),
        "required_paths_tracked": tracked,
        "tests_pass": tests["passed"] and tests["count"] is not None,
    }
    passed = all(checks.values())
    return {
        "status": "pass" if passed else "fail",
        "decision": "RETAIN_INCUMBENT" if passed else "INSUFFICIENT_EVIDENCE",
        "artifact": {
            "path": str(MODEL.relative_to(ROOT)),
            "sha256": sha256(MODEL),
            "deployment_strategy": artifact.get("deployment_strategy"),
        },
        "metrics": {
            "selected_posthoc_development_mape_percent": source["per_seed_metrics"][0]["mape_percent"],
            "native_replay_mape_percent_not_generalization": mape(native_pairs),
            "dense_25fps_simulation_mape_percent_not_generalization": mape(dense_pairs),
            "dense_mean_abs_drift_ml": statistics.mean(dense_drifts),
            "dense_max_abs_drift_ml": max(dense_drifts),
            "strict_nested_partial_pooling_mape_percent": partial["metrics"]["mape_percent"],
            "july_selected_repeatability_cv_percent_not_accuracy": july_cv,
            "latency_seconds": {
                "samples": latency_samples,
                "p95_conservative_max_of_5": latency_p95,
            },
        },
        "dropout_abstentions": dropout,
        "july_rows": july_rows,
        "attempted_research": {
            "strategy_study": str(STRATEGY.relative_to(ROOT)),
            "robustness_study": str(ROBUSTNESS.relative_to(ROOT)),
            "partial_pooling_study": str(PARTIAL.relative_to(ROOT)),
            "july_inventory": str(INVENTORY.relative_to(ROOT)),
            "fixed_modality_study": str(MODALITY_FIXED.relative_to(ROOT)),
            "nested_modality_study": str(MODALITY_NESTED.relative_to(ROOT)),
        },
        "checks": checks,
        "tests": tests,
        "claim_boundary": (
            "No accuracy challenger was promoted. The incumbent point strategy is retained with "
            "deterministic Windows 25 fps and sensor-quality hardening only. No independent "
            "wet-sample accuracy is claimed."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.parse_args()
    result = validate()
    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
