#!/usr/bin/env python3
"""Export the frozen type-conditioned sensor endpoint model for the site."""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
import statistics
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.ml_typewise_eval import load_runs  # noqa: E402
from auto_titrator.type_conditioned_sensor_live_model import ARTIFACT_TYPE  # noqa: E402
from auto_titrator.type_conditioned_sensor_live_model import (  # noqa: E402
    generate_union_candidates,
)
from tools.type_conditioned_sensor_sequence_search import (  # noqa: E402
    DEFAULT_INPUT_DIR,
    FEATURE_SUBSETS,
    TYPE_CONFIGS,
    active_feature_names,
    fit_candidate_scorer,
)


DEFAULT_SUMMARY = Path("data/ml/type_conditioned_sensor_sequence_search/summary.json")
DEFAULT_OUTPUT = Path("data/labeled/type-conditioned-sensor-endpoint-ranker.pkl")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _median_positive_volume_step(runs, titration_type: str) -> float:
    steps = []
    for run in runs:
        if run.titration_type != titration_type:
            continue
        volumes = [
            float(row["injected_volume_ml"])
            for row in run.rows
            if row.get("injected_volume_ml") not in (None, "")
        ]
        steps.extend(
            after - before
            for before, after in zip(volumes, volumes[1:])
            if after > before
        )
    if not steps:
        raise ValueError(f"no positive volume steps for {titration_type}")
    return float(statistics.median(steps))


def export_model(
    *,
    input_dir: str | Path,
    summary_path: str | Path,
    output_path: str | Path,
) -> Path:
    runs = load_runs(input_dir)
    if len(runs) != 12:
        raise ValueError(f"expected 12 development runs, found {len(runs)}")
    summary_file = Path(summary_path)
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    per_seed = summary.get("per_seed_metrics") or []
    if not per_seed:
        raise ValueError("development summary has no metrics")
    development_mape = float(per_seed[0]["mape_percent"])

    candidate_sets = {
        str(run.path): generate_union_candidates(run.rows) for run in runs
    }
    if any(not candidates for candidates in candidate_sets.values()):
        raise ValueError("one or more development runs produced no candidates")

    models = {}
    for titration_type, config in sorted(TYPE_CONFIGS.items()):
        global_estimator = None
        type_estimator = None
        if config.global_weight > 0.0:
            global_estimator = fit_candidate_scorer(runs, candidate_sets, config)
        if config.global_weight < 1.0:
            type_runs = [run for run in runs if run.titration_type == titration_type]
            if not type_runs:
                raise ValueError(f"no development runs for {titration_type}")
            type_estimator = fit_candidate_scorer(type_runs, candidate_sets, config)
        config_dict = asdict(config)
        config_dict["feature_indices"] = list(FEATURE_SUBSETS[config.feature_subset])
        models[titration_type] = {
            "config": config_dict,
            "active_feature_names": list(active_feature_names(config)),
            "global_estimator": global_estimator,
            "type_estimator": type_estimator,
            "global_training_run_count": len(runs) if global_estimator is not None else 0,
            "type_training_run_count": sum(
                run.titration_type == titration_type for run in runs
            )
            if type_estimator is not None
            else 0,
            "fold_estimators": [],
            "training_median_positive_volume_step_ml": _median_positive_volume_step(
                runs, titration_type
            ),
        }
        for omitted in runs:
            fold_runs = [run for run in runs if run.path != omitted.path]
            fold_global_estimator = (
                fit_candidate_scorer(fold_runs, candidate_sets, config)
                if config.global_weight > 0.0
                else None
            )
            fold_type_estimator = None
            if config.global_weight < 1.0:
                fold_type_runs = [
                    run
                    for run in fold_runs
                    if run.titration_type == titration_type
                ]
                fold_type_estimator = fit_candidate_scorer(
                    fold_type_runs, candidate_sets, config
                )
            models[titration_type]["fold_estimators"].append(
                {
                    "omitted_run": omitted.path.name,
                    "global_estimator": fold_global_estimator,
                    "type_estimator": fold_type_estimator,
                }
            )

    artifact = {
        "artifact_type": ARTIFACT_TYPE,
        "model_key": "type-conditioned-sensor-endpoint-v1",
        "prediction_scope": "completed_csv_post_run",
        "deployment_strategy": "median_of_12_leave_one_run_out_rankers",
        "development_mape_percent": development_mape,
        "source_summary": str(summary_file),
        "training_run_count": len(runs),
        "model_inputs": "visible and thermal sensor candidate features plus known titration type",
        "models": models,
        "provenance": {
            "summary_sha256": _sha256(summary_file),
            "training_csv_sha256": {
                run.path.name: _sha256(run.path) for run in sorted(runs, key=lambda item: item.path.name)
            },
        },
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        pickle.dump(artifact, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)
    output = export_model(
        input_dir=args.input_dir,
        summary_path=args.summary,
        output_path=args.output,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
