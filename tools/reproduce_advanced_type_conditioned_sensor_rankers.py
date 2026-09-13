#!/usr/bin/env python3
"""Focused independent refit of the selected configurations for three seeds."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import search_advanced_type_conditioned_sensor_rankers as search


def main() -> int:
    retained = (
        search.REPO / "docs/report_evidence_no_new_wet/model_search_audit"
        / "advanced_ranker_search"
    )
    artifacts = search.RESULTS if (search.RESULTS / "summary.json").is_file() else retained
    summary = json.loads((artifacts / "summary.json").read_text(encoding="utf-8"))
    selected = {item["titration_type"]: item for item in summary["result"]["selected_configs"]}
    runs = search.load_runs(search.DATA)
    sets = {str(run.path): search.generate_union_candidates(run.rows) for run in runs}
    assert search.source_sha256() == search.EXPECTED_UNION_SHA256
    assert search.union_signature(sets) == search.EXPECTED_SIGNATURE

    all_rows = []
    signatures = []
    for seed in search.SEEDS:
        np.random.seed(seed)
        seed_rows = []
        for test in runs:
            chosen = selected[test.titration_type]
            spec = search.Spec(**chosen["spec"])
            outer = [run for run in runs if run.path != test.path]
            assert test.path not in {run.path for run in outer}
            same_type = [run for run in outer if run.titration_type == test.titration_type]
            candidates = sets[str(test.path)]
            global_scores = search.score_one(outer, candidates, sets, spec)
            type_scores = search.score_one(same_type, candidates, sets, spec)
            scores = (
                float(chosen["global_weight"]) * search.normalize(global_scores, chosen["normalization"])
                + float(chosen["same_type_weight"]) * search.normalize(type_scores, chosen["normalization"])
            )
            top_k = 0 if chosen["top_k"] == "all" else int(chosen["top_k"])
            boundary = search.aggregate(candidates, scores, (top_k, chosen["temperature"], chosen["top_blend"]))
            predicted = float(test.rows[boundary]["injected_volume_ml"])
            actual = float(test.theoretical_equivalence_volume_ml)
            row = {
                "seed": seed, "run_name": test.path.name, "titration_type": test.titration_type,
                "selected_boundary_audit_only": boundary, "predicted_equivalence_volume_ml": predicted,
                "actual_equivalence_volume_ml": actual, "ape_percent": abs(predicted - actual) / actual * 100.0,
                "config_id": chosen["config_id"], "outer_test_excluded": True,
            }
            seed_rows.append(row)
            all_rows.append(row)
        signatures.append(json.dumps([
            (row["run_name"], row["selected_boundary_audit_only"], row["predicted_equivalence_volume_ml"])
            for row in seed_rows
        ], sort_keys=True))
    assert len(set(signatures)) == 1

    with (artifacts / "exact_predictions.csv").open(newline="", encoding="utf-8") as handle:
        expected = {
            row["run_name"]: (int(row["selected_boundary_audit_only"]), float(row["predicted_equivalence_volume_ml"]))
            for row in csv.DictReader(handle)
        }
    for row in all_rows:
        assert expected[row["run_name"]] == (
            row["selected_boundary_audit_only"], row["predicted_equivalence_volume_ml"]
        )

    search.write_csv(search.RESULTS / "focused_three_seed_refit.csv", all_rows)
    result = {
        "seeds": search.SEEDS,
        "all_predictions_identical": True,
        "matches_search_artifact": True,
        "outer_test_excluded_each_refit": True,
        "typewise_mape_percent": float(np.mean([row["ape_percent"] for row in all_rows[:len(runs)]])),
        "source_sha256": search.source_sha256(),
        "union_signature": search.union_signature(sets),
    }
    (search.RESULTS / "focused_refit_verification.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
