#!/usr/bin/env python3
"""Professor-critic validator for the Windows endpoint deployment model."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.ml_typewise_eval import CsvRun, load_runs  # noqa: E402
from auto_titrator.type_conditioned_sensor_live_model import (  # noqa: E402
    _aggregate_boundary,
    _combined_candidate_scores,
    generate_union_candidates,
    load_type_conditioned_sensor_model,
    predict_type_conditioned_sensor_equivalence,
)
from tools.type_conditioned_sensor_sequence_search import (  # noqa: E402
    TYPE_CONFIGS,
    aggregate_boundary,
    candidate_scores,
    fit_candidate_scorer,
    forbidden_features,
    normalize_scores,
)


MODEL_PATH = ROOT / "data/labeled/type-conditioned-sensor-endpoint-ranker.pkl"
JUNE_DIR = ROOT / "머신러닝용 파일모음"
JULY_ARCHIVE = ROOT / "Downloads.zip"
JULY_RUNS = (
    "auto-titration-live-20260726-150424-session-5.csv",
    "auto-titration-live-20260726-151233-session-7.csv",
    "auto-titration-live-20260726-151632-session-8.csv",
)


def _volume_for_pair(
    entry: Mapping[str, Any],
    estimator_pair: Mapping[str, Any],
    run: CsvRun,
    candidates: Sequence[Any],
) -> float:
    config = entry["config"]
    scores = _combined_candidate_scores(estimator_pair, candidates, config)
    frame, _, _ = _aggregate_boundary(candidates, scores, config)
    frame = max(0, min(frame, len(run.rows) - 1))
    return float(run.rows[frame]["injected_volume_ml"])


def _mape(rows: Sequence[tuple[float, float]]) -> float:
    return statistics.mean(abs(predicted - actual) / actual * 100.0 for actual, predicted in rows)


def validate(*, run_tests: bool = True) -> dict[str, Any]:
    artifact = load_type_conditioned_sensor_model(MODEL_PATH)
    if artifact is None:
        raise FileNotFoundError(MODEL_PATH)
    expected_types = set(TYPE_CONFIGS)
    model_types = set(artifact["models"])
    fold_counts = {
        key: len(value.get("fold_estimators") or [])
        for key, value in artifact["models"].items()
    }
    blocked_features = {
        key: forbidden_features(value.get("active_feature_names") or [])
        for key, value in artifact["models"].items()
    }

    june_runs = load_runs(JUNE_DIR)
    june_candidates = {
        str(run.path): generate_union_candidates(run.rows) for run in june_runs
    }
    full_fit_rows: list[tuple[float, float]] = []
    ensemble_rows: list[tuple[float, float]] = []
    oob_rows: list[tuple[float, float]] = []
    for run in june_runs:
        entry = artifact["models"][run.titration_type]
        candidates = june_candidates[str(run.path)]
        actual = float(run.theoretical_equivalence_volume_ml)
        full_fit = _volume_for_pair(entry, entry, run, candidates)
        full_fit_rows.append((actual, full_fit))
        ensemble = predict_type_conditioned_sensor_equivalence(
            artifact, run.rows, run.titration_type
        )["predicted_equivalence_volume_ml"]
        ensemble_rows.append((actual, float(ensemble)))
        fold = next(
            item
            for item in entry["fold_estimators"]
            if item["omitted_run"] == run.path.name
        )
        oob_rows.append((actual, _volume_for_pair(entry, fold, run, candidates)))

    type_only_rows: list[tuple[float, float]] = []
    for test in june_runs:
        train = [
            run
            for run in june_runs
            if run.path != test.path and run.titration_type == test.titration_type
        ]
        config = TYPE_CONFIGS[test.titration_type]
        estimator = fit_candidate_scorer(train, june_candidates, config)
        candidates = june_candidates[str(test.path)]
        scores = normalize_scores(
            candidate_scores(estimator, candidates, config),
            config.score_normalization,
        )
        frame, _, _ = aggregate_boundary(candidates, scores, config)
        frame = max(0, min(frame, len(test.rows) - 1))
        predicted = float(test.rows[frame]["injected_volume_ml"])
        type_only_rows.append((float(test.theoretical_equivalence_volume_ml), predicted))

    with tempfile.TemporaryDirectory(prefix="endpoint_model_july_") as temp:
        with zipfile.ZipFile(JULY_ARCHIVE) as archive:
            archive.extractall(temp)
        available = {run.path.name: run for run in load_runs(temp)}
        july_concentrations = []
        july_predictions = []
        for name in JULY_RUNS:
            run = available[name]
            result = predict_type_conditioned_sensor_equivalence(
                artifact, run.rows, run.titration_type
            )
            volume = float(result["predicted_equivalence_volume_ml"])
            concentration = (
                float(run.rows[0]["titrant_concentration_M"])
                * volume
                / float(run.rows[0]["sample_volume_ml"])
            )
            july_concentrations.append(concentration)
            july_predictions.append(
                {"source_file": name, "endpoint_ml": volume, "concentration_M": concentration}
            )
    july_cv = statistics.stdev(july_concentrations) / statistics.mean(july_concentrations) * 100.0

    benchmark_run = june_runs[0]
    started = time.perf_counter()
    predict_type_conditioned_sensor_equivalence(
        artifact, benchmark_run.rows, benchmark_run.titration_type
    )
    prediction_seconds = time.perf_counter() - started

    collector_source = (ROOT / "tools/windows_live_collect.py").read_text(encoding="utf-8")
    endpoint_priority = collector_source.index("if self._apply_endpoint_prediction_model_locked()")
    old_priority = collector_source.index("if self._apply_typewise_prediction_model_locked()")
    causal_auto_stop_preserved = "ColorChangeAutoStopController(\n            typewise_prediction_model" in collector_source

    tests = {
        "ran": run_tests,
        "passed": None if not run_tests else False,
        "count": None,
        "failure": "",
    }
    if run_tests:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "tests.test_type_conditioned_sensor_live_model",
                "tests.test_typewise_live_model",
                "tests.test_windows_live_collect",
                "tests.test_website_assets",
                "tests.test_dashboard_server",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        tests["passed"] = completed.returncode == 0
        tests["failure"] = "" if tests["passed"] else (completed.stdout + completed.stderr)[-4000:]
        combined = completed.stdout + completed.stderr
        marker = "Ran "
        if marker in combined:
            try:
                tests["count"] = int(combined.rsplit(marker, 1)[1].split(" test", 1)[0])
            except (ValueError, IndexError):
                pass

    metrics = {
        "selected_configuration_oob_mape_percent": _mape(oob_rows),
        "full_fit_replay_mape_percent": _mape(full_fit_rows),
        "fold_ensemble_replay_mape_percent": _mape(ensemble_rows),
        "same_type_only_loro_mape_percent": _mape(type_only_rows),
        "july_unknown_repeatability_cv_percent": july_cv,
        "single_run_prediction_seconds": prediction_seconds,
    }
    checks = {
        "four_routes": model_types == expected_types,
        "twelve_fold_estimators_per_route": set(fold_counts.values()) == {12},
        "no_forbidden_model_features": not any(blocked_features.values()),
        "oob_reproduces_selected_development_result": metrics[
            "selected_configuration_oob_mape_percent"
        ]
        <= 0.31,
        "ensemble_improves_full_fit_replay": metrics[
            "fold_ensemble_replay_mape_percent"
        ]
        <= metrics["full_fit_replay_mape_percent"],
        "ensemble_beats_same_type_only_loro": metrics[
            "fold_ensemble_replay_mape_percent"
        ]
        < metrics["same_type_only_loro_mape_percent"],
        "july_repeatability_preserved": july_cv <= 1.0,
        "prediction_latency_within_gate": prediction_seconds <= 2.0,
        "site_uses_endpoint_model_before_fallback": endpoint_priority < old_priority,
        "causal_auto_stop_model_preserved": causal_auto_stop_preserved,
        "tests_pass": bool(tests["ran"] and tests["passed"]),
    }
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "artifact": str(MODEL_PATH.relative_to(ROOT)),
        "deployment_strategy": artifact.get("deployment_strategy"),
        "model_types": sorted(model_types),
        "fold_counts": fold_counts,
        "blocked_features": blocked_features,
        "metrics": metrics,
        "july_predictions": july_predictions,
        "accuracy_scope": (
            "June values are development/OOB or replay diagnostics. July has no standardized "
            "truth and supports repeatability only, not accuracy."
        ),
        "checks": checks,
        "tests": tests,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    result = validate(run_tests=not args.skip_tests)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
