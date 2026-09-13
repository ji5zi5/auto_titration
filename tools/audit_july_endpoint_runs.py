#!/usr/bin/env python3
"""Inventory every July CSV without using predictions to redefine eligibility."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.ml_typewise_eval import load_runs  # noqa: E402


DEFAULT_ARCHIVE = ROOT / "Downloads.zip"
DEFAULT_OUTPUT = ROOT / "data/labeled/july-endpoint-run-inventory.json"
PARTICIPANT_DESIGNATED_REPEATS = {
    "auto-titration-live-20260726-150424-session-5.csv",
    "auto-titration-live-20260726-151233-session-7.csv",
    "auto-titration-live-20260726-151632-session-8.csv",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_inventory(archive_path: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="july_endpoint_inventory_") as temp:
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(temp)
        runs = load_runs(temp)
        entries = []
        for run in sorted(runs, key=lambda item: item.path.name):
            first = run.rows[0]
            old_prediction = next(
                (
                    row.get("sample_concentration_from_predicted_equivalence_M")
                    for row in run.rows
                    if row.get("sample_concentration_from_predicted_equivalence_M")
                    not in (None, "")
                ),
                None,
            )
            selected = run.path.name in PARTICIPANT_DESIGNATED_REPEATS
            entries.append(
                {
                    "source_file": run.path.name,
                    "sha256": sha256(run.path),
                    "row_count": len(run.rows),
                    "titration_type": run.titration_type,
                    "recorded_indicator": first.get("indicator"),
                    "recorded_nominal_concentration_M": first.get(
                        "sample_concentration_M"
                    ),
                    "recorded_max_injected_volume_ml": max(
                        float(row["injected_volume_ml"])
                        for row in run.rows
                        if row.get("injected_volume_ml") not in (None, "")
                    ),
                    "recorded_old_prediction_M_audit_only": old_prediction,
                    "participant_designated_same_solution_repeat": selected,
                    "analysis_scope": (
                        "descriptive_repeatability_only"
                        if selected
                        else "inventory_only_not_used_for_model_selection_or_accuracy"
                    ),
                }
            )
    return {
        "schema_version": "july_endpoint_run_inventory_v1",
        "archive": archive_path.name,
        "archive_sha256": sha256(archive_path),
        "loadable_run_count": len(entries),
        "participant_designated_repeat_count": sum(
            entry["participant_designated_same_solution_repeat"] for entry in entries
        ),
        "selection_policy": (
            "Sessions 5, 7, and 8 preserve the participant-designated same-solution "
            "set. No July run or prediction is used to select the deployed model."
        ),
        "accuracy_claim_allowed": False,
        "runs": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = build_inventory(args.archive)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
