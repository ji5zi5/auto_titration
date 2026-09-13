#!/usr/bin/env python3
"""Validate the existing-data-only science-fair report evidence bundle.

The validator intentionally uses only the Python standard library.  Every path
can be overridden so the same checks can run against small test fixtures.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = Path("머신러닝용 파일모음")
DEFAULT_EVIDENCE_DIR = Path("data/analysis/report_evidence_no_new_wet")
DEFAULT_REPORT = Path("docs/report_evidence_no_new_wet/보고서_교체문안.md")
DEFAULT_MANIFEST_CANDIDATES = (
    Path("docs/report_evidence_no_new_wet/claim_source_manifest.csv"),
    DEFAULT_EVIDENCE_DIR / "claim_source_manifest.json",
    DEFAULT_EVIDENCE_DIR / "claim_source_manifest.csv",
    Path("docs/science_fair_report_claim_source_table.md"),
)

EXPECTED_RUNS = 12
EXPECTED_ROWS = 1822
EXPECTED_METRICS: dict[str, dict[str, float]] = {
    "color_only": {
        "mae_ml": 0.5477698333333327,
        "rmse_ml": 0.7536889758525498,
        "mape_percent": 1.5520562499999986,
    },
    "thermal_only": {
        "mae_ml": 0.9172639166666663,
        "rmse_ml": 1.266932263917551,
        "mape_percent": 3.661546874999999,
    },
    "color_thermal_fusion": {
        "mae_ml": 0.4762603333333333,
        "rmse_ml": 0.8311218684544203,
        "mape_percent": 1.5244963888888887,
    },
}

REQUIRED_EVIDENCE_ARTIFACTS = (
    "raw_inventory.csv",
    "thermal_snr_by_run.csv",
    "thermal_contrast_by_run.csv",
    "thermal_contrast_window_sensitivity.csv",
    "color_vs_fusion_paired_errors.csv",
    "reproduced_modality_metrics.csv",
    "reaction_type_summary.csv",
    "model_stability_summary.csv",
    "summary.json",
    "report.md",
    "paired_endpoint_errors.png",
    "thermal_contrast_by_run.png",
    "thermal_contrast_vs_fusion_improvement.png",
)

NEGATION_MARKERS = (
    "not ",
    "no ",
    "neither ",
    "cannot ",
    "doesn't ",
    "does not ",
    "isn't ",
    "is not ",
    "without ",
    "금지",
    "아니",
    "않",
    "못",
    "미검증",
    "검증되지",
    "근거가 없",
    "입증하지",
    "주장하지",
)

UNSUPPORTED_WET_PATTERNS = (
    re.compile(r"\bindependent(?:ly)?\s+(?:wet\s+)?validat(?:ed|ion)\b", re.I),
    re.compile(r"\bwet(?:-experiment)?\s+validat(?:ed|ion)\b", re.I),
    re.compile(r"\bvalidated\s+(?:by|in|with)\s+(?:new\s+)?wet\s+experiments?\b", re.I),
    re.compile(r"(?:독립|습식|실제\s*적정)[^\n.!?。]{0,24}(?:검증|입증)(?:했|되었|완료|성공)"),
)

UNSUPPORTED_FLOW_PATTERNS = (
    re.compile(
        r"(?:0[.]962|0[.]99)[^\n.!?。]{0,80}"
        r"(?:precision|repeatab|accurac|정밀|반복성|정확|안정성)[^\n.!?。]*",
        re.I,
    ),
    re.compile(
        r"(?:precision|repeatab|accurac|정밀|반복성|정확|안정성)[^\n.!?。]{0,80}"
        r"(?:0[.]962|0[.]99)",
        re.I,
    ),
)


class ValidationPaths(NamedTuple):
    root: Path
    raw_dir: Path
    evidence_dir: Path
    report: Path
    manifest: Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _nonempty(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _float(value: object) -> float | None:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def validate_artifacts(paths: ValidationPaths, errors: list[str]) -> None:
    for name in REQUIRED_EVIDENCE_ARTIFACTS:
        path = paths.evidence_dir / name
        if not _nonempty(path):
            errors.append(f"required artifact missing or empty: {display_path(path, paths.root)}")
    if not _nonempty(paths.report):
        errors.append(f"required report missing or empty: {display_path(paths.report, paths.root)}")
    if not _nonempty(paths.manifest):
        errors.append(
            f"claim-source manifest missing or empty: {display_path(paths.manifest, paths.root)}"
        )


def validate_inventory(
    paths: ValidationPaths,
    errors: list[str],
    *,
    expected_runs: int,
    expected_rows: int,
) -> dict[str, int]:
    inventory_path = paths.evidence_dir / "raw_inventory.csv"
    if not inventory_path.is_file():
        return {"raw_runs": 0, "raw_rows": 0}
    try:
        inventory = read_csv(inventory_path)
    except (OSError, csv.Error) as exc:
        errors.append(f"cannot read raw inventory: {exc}")
        return {"raw_runs": 0, "raw_rows": 0}

    if len(inventory) != expected_runs:
        errors.append(f"raw run count mismatch: expected {expected_runs}, found {len(inventory)}")
    inventory_names: list[str] = []
    total_rows = 0
    for index, item in enumerate(inventory, start=2):
        name = str(item.get("raw_file", "")).strip()
        inventory_names.append(name)
        raw_path = paths.raw_dir / name
        if not name or not raw_path.is_file():
            errors.append(f"inventory raw file does not exist at row {index}: {name or '<empty>'}")
            continue
        expected_hash = str(item.get("sha256", "")).strip().lower()
        actual_hash = sha256_file(raw_path)
        if expected_hash != actual_hash:
            errors.append(f"sha256 mismatch for raw file: {name}")
        try:
            actual_rows = len(read_csv(raw_path))
        except (OSError, csv.Error) as exc:
            errors.append(f"cannot read raw CSV {name}: {exc}")
            continue
        listed_rows = item.get("row_count", "")
        try:
            listed_count = int(str(listed_rows).strip())
        except ValueError:
            errors.append(f"invalid inventory row_count for {name}: {listed_rows!r}")
        else:
            if listed_count != actual_rows:
                errors.append(
                    f"row count mismatch for {name}: inventory {listed_count}, actual {actual_rows}"
                )
        total_rows += actual_rows

    actual_names = sorted(path.name for path in paths.raw_dir.glob("*.csv") if path.is_file())
    if sorted(inventory_names) != actual_names:
        missing = sorted(set(actual_names) - set(inventory_names))
        extra = sorted(set(inventory_names) - set(actual_names))
        errors.append(f"raw inventory file set mismatch: unlisted={missing}, missing={extra}")
    if total_rows != expected_rows:
        errors.append(f"raw row count mismatch: expected {expected_rows}, found {total_rows}")
    return {"raw_runs": len(inventory), "raw_rows": total_rows}


def _compare_metrics(
    label: str, values: dict[str, Any], errors: list[str], *, tolerance: float
) -> None:
    n_runs = values.get("n_runs")
    try:
        parsed_runs = int(str(n_runs).strip())
    except (TypeError, ValueError):
        parsed_runs = -1
    if parsed_runs != EXPECTED_RUNS:
        errors.append(f"metric run count mismatch for {label}: expected 12, found {n_runs!r}")
    for metric, expected in EXPECTED_METRICS[label].items():
        actual = _float(values.get(metric))
        if actual is None or not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
            errors.append(
                f"metric mismatch for {label}.{metric}: expected {expected:.15g}, found {values.get(metric)!r}"
            )


def validate_metrics(paths: ValidationPaths, errors: list[str], *, tolerance: float) -> None:
    csv_path = paths.evidence_dir / "reproduced_modality_metrics.csv"
    summary_path = paths.evidence_dir / "summary.json"
    if csv_path.is_file():
        try:
            rows = read_csv(csv_path)
            by_modality = {str(row.get("modality", "")): row for row in rows}
            if set(by_modality) != set(EXPECTED_METRICS):
                errors.append(
                    "metric modality set mismatch: expected "
                    f"{sorted(EXPECTED_METRICS)}, found {sorted(by_modality)}"
                )
            for label in EXPECTED_METRICS:
                if label in by_modality:
                    _compare_metrics(label, by_modality[label], errors, tolerance=tolerance)
        except (OSError, csv.Error) as exc:
            errors.append(f"cannot read modality metrics CSV: {exc}")
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"cannot read summary JSON: {exc}")
            return
        if summary.get("raw_run_count") != EXPECTED_RUNS:
            errors.append("summary raw_run_count is not 12")
        if summary.get("raw_row_count") != EXPECTED_ROWS:
            errors.append("summary raw_row_count is not 1822")
        if summary.get("independent_validation") is not False:
            errors.append("summary must explicitly set independent_validation to false")
        values = summary.get("reproduced_prediction_metrics")
        if not isinstance(values, dict):
            errors.append("summary lacks reproduced_prediction_metrics")
        else:
            for label in EXPECTED_METRICS:
                item = values.get(label)
                if not isinstance(item, dict):
                    errors.append(f"summary lacks metrics for {label}")
                else:
                    _compare_metrics(label, item, errors, tolerance=tolerance)
        if summary.get("invalid_all_zero_thermal_row_count") != 11:
            errors.append("summary invalid_all_zero_thermal_row_count must be 11")
        paired = summary.get("paired_color_vs_fusion")
        if isinstance(paired, dict):
            expected_paired = {
                "mean_ape_improvement_percentage_points": 0.02755986111110953,
                "stratified_bootstrap_95_ci_low_percentage_points": -1.2048307777777805,
                "stratified_bootstrap_95_ci_high_percentage_points": 1.1477844444444398,
                "exact_sign_flip_two_sided_p_value": 0.97802734375,
                "exact_sign_test_two_sided_p_value": 0.7744140625,
            }
            for field, expected in expected_paired.items():
                actual = _float(paired.get(field))
                if actual is None or not math.isclose(
                    actual, expected, rel_tol=0.0, abs_tol=tolerance
                ):
                    errors.append(
                        f"paired evidence mismatch for {field}: expected {expected}, "
                        f"found {paired.get(field)!r}"
                    )
            if paired.get("fusion_better_run_count") not in (None, 7):
                errors.append("paired fusion_better_run_count must be 7")
            if paired.get("fusion_worse_run_count") not in (None, 5):
                errors.append("paired fusion_worse_run_count must be 5")
        else:
            errors.append("summary lacks paired_color_vs_fusion")
        claim_rules = summary.get("claim_fail_rules")
        if isinstance(claim_rules, dict):
            for name in (
                "fusion_improves_color",
                "fusion_equivalent_to_color",
                "universal_thermal_benefit",
                "conditional_thermal_benefit",
                "thermal_contrast_predicts_improvement",
            ):
                item = claim_rules.get(name)
                if not isinstance(item, dict) or item.get("pass") is not False:
                    errors.append(f"unsupported claim rule must fail: {name}")
        else:
            errors.append("summary lacks claim_fail_rules")


def _segments(text: str) -> Iterable[str]:
    for segment in re.split(r"(?<=[.!?。])\s+|\n+", text):
        stripped = segment.strip()
        if stripped:
            yield stripped


def _is_negated(segment: str) -> bool:
    lowered = segment.casefold()
    return any(marker in lowered for marker in NEGATION_MARKERS)


def validate_report(paths: ValidationPaths, errors: list[str]) -> None:
    if not paths.report.is_file():
        return
    try:
        text = paths.report.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read report: {exc}")
        return
    lowered = text.casefold()
    btb_present = "btb" in lowered and (
        "bromothymol_blue" in lowered or "bromothymol blue" in lowered or "브로모티몰" in text
    )
    correction_present = any(token in lowered for token in ("correct", "metadata error", "정정", "기록 오류"))
    raw_preserved = any(
        token in lowered
        for token in (
            "raw csv bytes remain unchanged",
            "raw csvs unchanged",
            "raw csv",
            "source data",
            "원본 csv",
            "원자료",
        )
    ) and any(
        token in lowered
        for token in ("unchanged", "not modify", "without modifying", "retained", "보존", "수정하지")
    )
    if not (btb_present and "methyl_orange" in lowered and correction_present and raw_preserved):
        errors.append(
            "report lacks complete BTB correction (methyl_orange error, BTB correction, raw preservation)"
        )
    participant_reported = any(
        token in lowered
        for token in ("participant", "researcher reported", "연구 수행자", "사후 확인")
    )
    unverified_correction = any(
        token in lowered
        for token in (
            "not independently verified",
            "not independently revalidated",
            "no contemporaneous run-linked",
            "미독립검증",
            "독립적으로 검증되지",
            "당시 기록을 확인하지 못",
            "1차 기록을 찾지 못",
        )
    )
    if btb_present and not (participant_reported and unverified_correction):
        errors.append(
            "BTB correction must be labeled participant-reported and not independently verified"
        )

    required_evidence_tokens = {
        "primary paired improvement": ("0.027", "0.028"),
        "stratified CI lower bound": ("-1.205", "-1.204"),
        "stratified CI upper bound": ("1.148", "1.147"),
        "exact sign-flip p-value": ("0.978",),
        "exact sign-test p-value": ("0.774",),
        "robust MAD method": ("mad",),
        "normalized thermal windows": ("0.05", "0.20", "0.95", "1.05"),
    }
    for label, alternatives in required_evidence_tokens.items():
        if label == "normalized thermal windows":
            if not all(token in lowered for token in alternatives):
                errors.append(f"report lacks current {label}")
        elif not any(token in lowered for token in alternatives):
            errors.append(f"report lacks current {label}")
    for stale in ("-0.410", "0.470 ml", "0.781", "0~10%", "0–10%"):
        if stale in lowered:
            errors.append(f"report contains superseded analysis value/method: {stale}")

    pulse_segments = [segment for segment in _segments(text) if re.search(r"pulse|펄스|점적", segment, re.I)]
    if not pulse_segments:
        errors.append("report must describe the pulse module as dry/software-only")
    elif not any(
        re.search(r"software[- ]only|dry(?:[- ]test)?|simulation|소프트웨어(?:만| 전용| 시험)|건식|모의", segment, re.I)
        for segment in pulse_segments
    ):
        errors.append("pulse module is not marked dry/software-only in the report")

    for segment in _segments(text):
        if _is_negated(segment):
            continue
        if any(pattern.search(segment) for pattern in UNSUPPORTED_WET_PATTERNS):
            errors.append(f"unsupported wet-validation claim: {segment}")
        if any(pattern.search(segment) for pattern in UNSUPPORTED_FLOW_PATTERNS):
            errors.append(f"unsupported flow-precision claim: {segment}")


def _json_source_values(value: Any, *, source_context: bool = False) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).casefold()
            context = "source" in normalized_key or (
                source_context
                and normalized_key in {"file", "files", "path", "paths", "artifact", "artifacts"}
            )
            yield from _json_source_values(child, source_context=context)
    elif isinstance(value, list):
        for child in value:
            yield from _json_source_values(child, source_context=source_context)
    elif source_context and isinstance(value, str):
        yield value


def _manifest_sources(path: Path) -> list[str]:
    suffix = path.suffix.casefold()
    if suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return list(_json_source_values(value))
    if suffix == ".csv":
        rows = read_csv(path)
        return [
            value
            for row in rows
            for key, value in row.items()
            if key.casefold() in {"source", "sources", "source_path", "source_paths"}
            and value.strip()
        ]
    if suffix in {".md", ".markdown"}:
        values: list[str] = []
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.lstrip().startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 3:
                values.extend(re.findall(r"`([^`]+)`", cells[2]))
        return values
    raise ValueError(f"unsupported manifest format: {path.suffix or '<none>'}")


def _clean_source(value: str) -> str:
    source = value.strip().split("#", 1)[0]
    source = re.sub(r":\d+(?:-\d+)?(?:,\s*\d+(?:-\d+)?)*$", "", source)
    return source.strip()


def validate_manifest(paths: ValidationPaths, errors: list[str]) -> int:
    if not paths.manifest.is_file():
        return 0
    try:
        raw_sources = _manifest_sources(paths.manifest)
    except (OSError, UnicodeError, csv.Error, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"cannot read claim-source manifest: {exc}")
        return 0
    sources: list[str] = []
    for raw_value in raw_sources:
        # CSV cells may list several sources separated by semicolons.
        sources.extend(part for part in re.split(r"\s*;\s*", raw_value) if part)
    local_sources = sorted(
        {
            _clean_source(source)
            for source in sources
            if _clean_source(source)
            and not re.match(r"^(?:https?|doi):", _clean_source(source), re.I)
        }
    )
    if not local_sources:
        errors.append("claim-source manifest contains no local source paths")
    for source in local_sources:
        source_path = Path(source)
        candidate = source_path if source_path.is_absolute() else paths.root / source_path
        if not candidate.exists():
            errors.append(f"manifest source does not exist: {source}")
    return len(local_sources)


def validate(
    paths: ValidationPaths,
    *,
    expected_runs: int = EXPECTED_RUNS,
    expected_rows: int = EXPECTED_ROWS,
    metric_tolerance: float = 1e-9,
) -> dict[str, Any]:
    errors: list[str] = []
    validate_artifacts(paths, errors)
    observed = validate_inventory(
        paths, errors, expected_runs=expected_runs, expected_rows=expected_rows
    )
    validate_metrics(paths, errors, tolerance=metric_tolerance)
    validate_report(paths, errors)
    observed["manifest_sources"] = validate_manifest(paths, errors)
    unique_errors = list(dict.fromkeys(errors))
    return {
        "passed": not unique_errors,
        "status": "passed" if not unique_errors else "failed",
        "observed": observed,
        "errors": unique_errors,
    }


def _default_manifest(root: Path) -> Path:
    for candidate in DEFAULT_MANIFEST_CANDIDATES:
        if resolve(root, candidate).exists():
            return candidate
    return DEFAULT_MANIFEST_CANDIDATES[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit one deterministic JSON object")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--claim-source-manifest", type=Path)
    parser.add_argument("--expected-runs", type=int, default=EXPECTED_RUNS)
    parser.add_argument("--expected-rows", type=int, default=EXPECTED_ROWS)
    parser.add_argument("--metric-tolerance", type=float, default=1e-9)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    manifest_arg = args.claim_source_manifest or _default_manifest(root)
    paths = ValidationPaths(
        root=root,
        raw_dir=resolve(root, args.raw_dir),
        evidence_dir=resolve(root, args.evidence_dir),
        report=resolve(root, args.report),
        manifest=resolve(root, manifest_arg),
    )
    try:
        result = validate(
            paths,
            expected_runs=args.expected_runs,
            expected_rows=args.expected_rows,
            metric_tolerance=args.metric_tolerance,
        )
    except Exception as exc:  # Keep CLI failures machine-readable and nonzero.
        result = {
            "passed": False,
            "status": "failed",
            "observed": {},
            "errors": [f"validator error: {type(exc).__name__}: {exc}"],
        }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    elif result["passed"]:
        print(
            "PASS: existing-data report evidence validated "
            f"({result['observed']['raw_runs']} runs / {result['observed']['raw_rows']} rows)"
        )
    else:
        print("FAIL: existing-data report evidence validation failed", file=sys.stderr)
        for error in result["errors"]:
            print(f"- {error}", file=sys.stderr)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
