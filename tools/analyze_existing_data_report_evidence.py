#!/usr/bin/env python3
"""Build a deterministic evidence report from the already-collected titration data.

This tool does not train models or alter source CSVs.  It audits the twelve raw
runs and recomputes descriptive/error statistics from stored prediction files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import random
import statistics
from pathlib import Path
from typing import Iterable, Sequence


BASELINE_START_FRACTION = 0.05
BASELINE_END_FRACTION = 0.20
ENDPOINT_START_FRACTION = 0.95
ENDPOINT_END_FRACTION = 1.05
FIXED_ENDPOINT_HALF_WIDTHS_ML = (0.5, 1.0, 2.0)
MIN_BASELINE_SAMPLES = 8
MIN_ENDPOINT_SAMPLES = 5
NEAR_ZERO_NOISE_C = 1e-12
BOOTSTRAP_SEED = 20260605
BOOTSTRAP_REPLICATES = 100_000
CORRELATION_PERMUTATION_SEED = 20260606
CORRELATION_PERMUTATIONS = 100_000

MODALITY_FILES = {
    "color_only": "selected_predictions_color_only.csv",
    "thermal_only": "selected_predictions_thermal_only.csv",
    "color_thermal_fusion": "selected_predictions_color_thermal_fusion.csv",
}

INVENTORY_FIELDS = [
    "run_id",
    "raw_file",
    "sha256",
    "row_count",
    "titration_type",
    "sample_concentration_M",
    "theoretical_equivalence_volume_ml",
    "recorded_indicator",
    "participant_reported_indicator_correction",
    "indicator_metadata_status",
]

SNR_FIELDS = [
    "run_id",
    "raw_file",
    "titration_type",
    "theoretical_equivalence_volume_ml",
    "baseline_volume_start_ml",
    "baseline_volume_end_ml",
    "endpoint_window_start_ml",
    "endpoint_window_end_ml",
    "baseline_n",
    "endpoint_n",
    "invalid_all_zero_thermal_rows",
    "invalid_all_zero_rows_in_baseline",
    "invalid_all_zero_rows_in_endpoint",
    "baseline_median_c",
    "endpoint_median_c",
    "signal_signed_delta_c",
    "signal_abs_delta_c",
    "baseline_noise_scaled_mad_c",
    "snr_ratio",
    "snr_db",
    "snr_status",
]

PAIRED_FIELDS = [
    "run_id",
    "raw_file",
    "titration_type",
    "actual_equivalence_volume_ml",
    "color_predicted_volume_ml",
    "fusion_predicted_volume_ml",
    "color_abs_error_ml",
    "fusion_abs_error_ml",
    "paired_improvement_ml",
    "color_ape_percent",
    "fusion_ape_percent",
    "paired_ape_improvement_percentage_points",
    "fusion_better",
]

METRIC_FIELDS = ["modality", "n_runs", "mae_ml", "rmse_ml", "mape_percent"]

SENSITIVITY_FIELDS = [
    "run_id",
    "raw_file",
    "titration_type",
    "window_name",
    "endpoint_window_start_ml",
    "endpoint_window_end_ml",
    "baseline_n",
    "endpoint_n",
    "signal_signed_delta_c",
    "baseline_noise_scaled_mad_c",
    "contrast_to_noise_ratio",
    "status",
]

TYPE_SUMMARY_FIELDS = [
    "titration_type",
    "n_runs",
    "valid_contrast_run_count",
    "median_contrast_to_noise_ratio",
    "mean_ape_improvement_percentage_points",
    "fusion_better_run_count",
    "fusion_worse_run_count",
]

STABILITY_FIELDS = [
    "probe",
    "configuration",
    "seed",
    "tree_multiplier",
    "mae_ml",
    "rmse_ml",
    "mape_percent",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite_float(value: object) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def run_id_from_row(row: dict[str, str], path: Path) -> str:
    session = row.get("csv_session_id", "").strip()
    return f"session-{session}" if session else path.stem


def reported_indicator_correction(titration_type: str, recorded: str) -> tuple[str, str]:
    if titration_type == "weak_acid_weak_base":
        return (
            "bromothymol_blue (BTB)",
            "participant_reported_not_independently_verified_raw_csv_retained",
        )
    return recorded, "raw_metadata_used"


def inventory_raw_runs(raw_dir: Path) -> tuple[list[dict[str, object]], dict[str, list[dict[str, str]]]]:
    inventory: list[dict[str, object]] = []
    rows_by_file: dict[str, list[dict[str, str]]] = {}
    paths = sorted(raw_dir.glob("*.csv"), key=lambda path: path.name)
    for path in paths:
        rows = read_csv(path)
        if not rows:
            raise ValueError(f"empty raw CSV: {path}")
        first = rows[0]
        required = (
            "titration_type",
            "sample_concentration_M",
            "theoretical_equivalence_volume_ml",
            "indicator",
            "injected_volume_ml",
            "thermal_roi_avg",
        )
        missing = [field for field in required if field not in first]
        if missing:
            raise ValueError(f"raw CSV {path} lacks columns: {', '.join(missing)}")
        participant_reported_indicator, indicator_status = reported_indicator_correction(
            first["titration_type"], first.get("indicator", "")
        )
        inventory.append(
            {
                "run_id": run_id_from_row(first, path),
                "raw_file": path.name,
                "sha256": sha256_file(path),
                "row_count": len(rows),
                "titration_type": first["titration_type"],
                "sample_concentration_M": finite_float(first["sample_concentration_M"]),
                "theoretical_equivalence_volume_ml": finite_float(
                    first["theoretical_equivalence_volume_ml"]
                ),
                "recorded_indicator": first.get("indicator", ""),
                "participant_reported_indicator_correction": participant_reported_indicator,
                "indicator_metadata_status": indicator_status,
            }
        )
        rows_by_file[path.name] = rows
    return inventory, rows_by_file


def is_invalid_all_zero_thermal_summary(row: dict[str, str]) -> bool:
    """Detect a provenance-level invalid ROI record, not a physical 0 °C value.

    The affected raw rows have every available ROI summary equal to exactly zero.
    A negative or isolated zero average accompanied by non-zero summaries remains valid.
    """

    fields = ("thermal_roi_avg", "thermal_roi_min", "thermal_roi_max", "thermal_roi_std")
    values = [finite_float(row.get(field)) for field in fields if field in row]
    finite = [value for value in values if value is not None]
    return bool(finite) and finite_float(row.get("thermal_roi_avg")) == 0.0 and all(
        abs(value) <= NEAR_ZERO_NOISE_C for value in finite
    )


def scaled_mad(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("MAD requires values")
    center = statistics.median(values)
    return 1.4826 * statistics.median(abs(value - center) for value in values)


def _thermal_contrast_for_window(
    inventory_row: dict[str, object],
    rows: Sequence[dict[str, str]],
    *,
    endpoint_start: float,
    endpoint_end: float,
) -> dict[str, object]:
    theory = float(inventory_row["theoretical_equivalence_volume_ml"])
    baseline_start = theory * BASELINE_START_FRACTION
    baseline_end = theory * BASELINE_END_FRACTION
    invalid_rows = [row for row in rows if is_invalid_all_zero_thermal_summary(row)]
    usable: list[tuple[float, float]] = []
    for row in rows:
        if is_invalid_all_zero_thermal_summary(row):
            continue
        volume = finite_float(row.get("injected_volume_ml"))
        temperature = finite_float(row.get("thermal_roi_avg"))
        if volume is not None and temperature is not None:
            usable.append((volume, temperature))
    baseline = [
        temperature
        for volume, temperature in usable
        if baseline_start <= volume <= baseline_end
    ]
    endpoint = [
        temperature
        for volume, temperature in usable
        if endpoint_start <= volume <= endpoint_end
    ]
    invalid_baseline = sum(
        1
        for row in invalid_rows
        if (volume := finite_float(row.get("injected_volume_ml"))) is not None
        and baseline_start <= volume <= baseline_end
    )
    invalid_endpoint = sum(
        1
        for row in invalid_rows
        if (volume := finite_float(row.get("injected_volume_ml"))) is not None
        and endpoint_start <= volume <= endpoint_end
    )
    result: dict[str, object] = {
        "run_id": inventory_row["run_id"],
        "raw_file": inventory_row["raw_file"],
        "titration_type": inventory_row["titration_type"],
        "theoretical_equivalence_volume_ml": theory,
        "baseline_volume_start_ml": baseline_start,
        "baseline_volume_end_ml": baseline_end,
        "endpoint_window_start_ml": endpoint_start,
        "endpoint_window_end_ml": endpoint_end,
        "baseline_n": len(baseline),
        "endpoint_n": len(endpoint),
        "invalid_all_zero_thermal_rows": len(invalid_rows),
        "invalid_all_zero_rows_in_baseline": invalid_baseline,
        "invalid_all_zero_rows_in_endpoint": invalid_endpoint,
        "baseline_median_c": statistics.median(baseline) if baseline else None,
        "endpoint_median_c": statistics.median(endpoint) if endpoint else None,
        "signal_signed_delta_c": None,
        "signal_abs_delta_c": None,
        "baseline_noise_scaled_mad_c": None,
        "snr_ratio": None,
        "snr_db": None,
        "snr_status": "ok",
    }
    if not usable:
        result["snr_status"] = "missing_valid_thermal_values"
        return result
    if len(baseline) < MIN_BASELINE_SAMPLES:
        result["snr_status"] = "insufficient_baseline_values"
        return result
    if len(endpoint) < MIN_ENDPOINT_SAMPLES:
        result["snr_status"] = "insufficient_endpoint_values"
        return result
    signal_signed = statistics.median(endpoint) - statistics.median(baseline)
    noise = scaled_mad(baseline)
    result["signal_signed_delta_c"] = signal_signed
    result["signal_abs_delta_c"] = abs(signal_signed)
    result["baseline_noise_scaled_mad_c"] = noise
    if noise <= NEAR_ZERO_NOISE_C:
        result["snr_status"] = "zero_or_near_zero_baseline_mad"
        return result
    ratio = abs(signal_signed) / noise
    result["snr_ratio"] = ratio
    if abs(signal_signed) <= NEAR_ZERO_NOISE_C:
        result["snr_status"] = "zero_or_near_zero_signal"
        return result
    result["snr_db"] = 20.0 * math.log10(ratio)
    return result


def thermal_snr_for_run(
    inventory_row: dict[str, object], rows: Sequence[dict[str, str]]
) -> dict[str, object]:
    """Primary operational endpoint-to-baseline contrast-to-noise result.

    This is intentionally not called instrument S/N: it is a secondary contrast
    statistic computed from the already-recorded ROI temperature summaries.
    """

    theory = finite_float(inventory_row["theoretical_equivalence_volume_ml"])
    if theory is None or theory <= 0:
        raise ValueError(f"invalid theoretical endpoint for {inventory_row['raw_file']}")
    return _thermal_contrast_for_window(
        inventory_row,
        rows,
        endpoint_start=theory * ENDPOINT_START_FRACTION,
        endpoint_end=theory * ENDPOINT_END_FRACTION,
    )


def thermal_sensitivity_rows(
    inventory_row: dict[str, object], rows: Sequence[dict[str, str]]
) -> list[dict[str, object]]:
    theory = float(inventory_row["theoretical_equivalence_volume_ml"])
    windows = [("normalized_0.95_to_1.05", theory * 0.95, theory * 1.05)]
    windows.extend(
        (f"fixed_plus_minus_{half_width:g}_ml", theory - half_width, theory + half_width)
        for half_width in FIXED_ENDPOINT_HALF_WIDTHS_ML
    )
    output: list[dict[str, object]] = []
    for name, start, end in windows:
        result = _thermal_contrast_for_window(
            inventory_row, rows, endpoint_start=start, endpoint_end=end
        )
        output.append(
            {
                "run_id": result["run_id"],
                "raw_file": result["raw_file"],
                "titration_type": result["titration_type"],
                "window_name": name,
                "endpoint_window_start_ml": start,
                "endpoint_window_end_ml": end,
                "baseline_n": result["baseline_n"],
                "endpoint_n": result["endpoint_n"],
                "signal_signed_delta_c": result["signal_signed_delta_c"],
                "baseline_noise_scaled_mad_c": result["baseline_noise_scaled_mad_c"],
                "contrast_to_noise_ratio": result["snr_ratio"],
                "status": result["snr_status"],
            }
        )
    return output


def prediction_rows(path: Path) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for row in read_csv(path):
        raw_file = Path(row.get("run_path", "").replace("\\", "/")).name
        if not raw_file:
            raise ValueError(f"prediction without run_path in {path}")
        if raw_file in result:
            raise ValueError(f"duplicate prediction for {raw_file} in {path}")
        actual = finite_float(row.get("actual_equivalence_volume_ml"))
        predicted = finite_float(row.get("predicted_equivalence_volume_ml"))
        if actual is None or predicted is None:
            raise ValueError(f"non-numeric prediction for {raw_file} in {path}")
        result[raw_file] = {
            "actual": actual,
            "predicted": predicted,
            "titration_type": row.get("titration_type", ""),
        }
    return result


def error_metrics(predictions: Iterable[dict[str, object]]) -> dict[str, float | int]:
    rows = list(predictions)
    if not rows:
        raise ValueError("cannot calculate metrics for zero predictions")
    errors = [float(row["predicted"]) - float(row["actual"]) for row in rows]
    actuals = [float(row["actual"]) for row in rows]
    if any(actual == 0 for actual in actuals):
        raise ValueError("MAPE is undefined for zero actual endpoints")
    return {
        "n_runs": len(rows),
        "mae_ml": statistics.fmean(abs(error) for error in errors),
        "rmse_ml": math.sqrt(statistics.fmean(error * error for error in errors)),
        "mape_percent": 100.0
        * statistics.fmean(abs(error) / abs(actual) for error, actual in zip(errors, actuals)),
    }


def paired_error_rows(
    inventory: Sequence[dict[str, object]],
    color: dict[str, dict[str, object]],
    fusion: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    expected = {str(row["raw_file"]) for row in inventory}
    for label, predictions in (("color", color), ("fusion", fusion)):
        if set(predictions) != expected:
            missing = sorted(expected - set(predictions))
            extra = sorted(set(predictions) - expected)
            raise ValueError(f"{label} run mismatch; missing={missing}, extra={extra}")
    output: list[dict[str, object]] = []
    for item in inventory:
        raw_file = str(item["raw_file"])
        color_row, fusion_row = color[raw_file], fusion[raw_file]
        actual = float(color_row["actual"])
        if not math.isclose(actual, float(fusion_row["actual"]), abs_tol=1e-12):
            raise ValueError(f"actual endpoint mismatch for {raw_file}")
        theory = float(item["theoretical_equivalence_volume_ml"])
        if not math.isclose(actual, theory, abs_tol=1e-9):
            raise ValueError(f"prediction actual differs from raw theory for {raw_file}")
        color_error = abs(float(color_row["predicted"]) - actual)
        fusion_error = abs(float(fusion_row["predicted"]) - actual)
        improvement = color_error - fusion_error
        color_ape = 100.0 * color_error / abs(actual)
        fusion_ape = 100.0 * fusion_error / abs(actual)
        output.append(
            {
                "run_id": item["run_id"],
                "raw_file": raw_file,
                "titration_type": item["titration_type"],
                "actual_equivalence_volume_ml": actual,
                "color_predicted_volume_ml": color_row["predicted"],
                "fusion_predicted_volume_ml": fusion_row["predicted"],
                "color_abs_error_ml": color_error,
                "fusion_abs_error_ml": fusion_error,
                "paired_improvement_ml": improvement,
                "color_ape_percent": color_ape,
                "fusion_ape_percent": fusion_ape,
                "paired_ape_improvement_percentage_points": color_ape - fusion_ape,
                "fusion_better": improvement > 0,
            }
        )
    return output


def linear_quantile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("quantile requires values")
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def paired_bootstrap_ci(
    improvements: Sequence[float], *, seed: int, replicates: int
) -> tuple[float, float]:
    if not improvements or replicates < 1:
        raise ValueError("bootstrap requires values and at least one replicate")
    rng = random.Random(seed)
    n = len(improvements)
    means = sorted(
        statistics.fmean(improvements[rng.randrange(n)] for _ in range(n))
        for _ in range(replicates)
    )
    return linear_quantile(means, 0.025), linear_quantile(means, 0.975)


def stratified_paired_bootstrap_ci(
    rows: Sequence[dict[str, object]],
    *,
    value_field: str,
    seed: int,
    replicates: int,
) -> tuple[float, float]:
    """Percentile CI resampling paired runs within each reaction-type stratum."""

    if not rows or replicates < 1:
        raise ValueError("stratified bootstrap requires rows and at least one replicate")
    strata: dict[str, list[float]] = {}
    for row in rows:
        strata.setdefault(str(row["titration_type"]), []).append(float(row[value_field]))
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(replicates):
        sample: list[float] = []
        for key in sorted(strata):
            values = strata[key]
            sample.extend(values[rng.randrange(len(values))] for _ in range(len(values)))
        means.append(statistics.fmean(sample))
    means.sort()
    return linear_quantile(means, 0.025), linear_quantile(means, 0.975)


def exact_sign_flip_p_value(improvements: Sequence[float]) -> float:
    """Two-sided exact randomization p-value for the paired mean improvement."""
    if not improvements:
        raise ValueError("sign-flip test requires values")
    observed = abs(statistics.fmean(improvements))
    tolerance = 1e-15
    extreme = 0
    total = 0
    for signs in itertools.product((-1.0, 1.0), repeat=len(improvements)):
        statistic = abs(statistics.fmean(sign * value for sign, value in zip(signs, improvements)))
        extreme += statistic >= observed - tolerance
        total += 1
    return extreme / total


def exact_sign_test_p_value(improvements: Sequence[float]) -> float:
    nonzero = [value for value in improvements if abs(value) > 1e-15]
    if not nonzero:
        return 1.0
    positives = sum(value > 0 for value in nonzero)
    tail = min(positives, len(nonzero) - positives)
    probability = 2.0 * sum(
        math.comb(len(nonzero), index) for index in range(tail + 1)
    ) / (2 ** len(nonzero))
    return min(1.0, probability)


def average_ranks(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(indexed):
        end = index + 1
        while end < len(indexed) and indexed[end][1] == indexed[index][1]:
            end += 1
        rank = ((index + 1) + end) / 2.0
        for original_index, _ in indexed[index:end]:
            ranks[original_index] = rank
        index = end
    return ranks


def pearson_correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("correlation requires equally sized sequences of length at least two")
    left_mean, right_mean = statistics.fmean(left), statistics.fmean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_ss = sum((x - left_mean) ** 2 for x in left)
    right_ss = sum((y - right_mean) ** 2 for y in right)
    if left_ss <= 0 or right_ss <= 0:
        raise ValueError("correlation is undefined for a constant sequence")
    return numerator / math.sqrt(left_ss * right_ss)


def spearman_correlation(left: Sequence[float], right: Sequence[float]) -> float:
    return pearson_correlation(average_ranks(left), average_ranks(right))


def spearman_permutation_p_value(
    left: Sequence[float],
    right: Sequence[float],
    *,
    seed: int,
    permutations: int,
) -> tuple[float, float]:
    """Fixed-seed exploratory Monte Carlo two-sided permutation result."""

    observed = spearman_correlation(left, right)
    rng = random.Random(seed)
    shuffled = list(right)
    extreme = 0
    for _ in range(permutations):
        rng.shuffle(shuffled)
        statistic = spearman_correlation(left, shuffled)
        extreme += abs(statistic) >= abs(observed) - 1e-15
    return observed, (extreme + 1) / (permutations + 1)


def csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.9f}"
    return value


def write_csv(path: Path, rows: Sequence[dict[str, object]], fields: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field)) for field in fields})


def reaction_type_summaries(
    snr_rows: Sequence[dict[str, object]], paired_rows: Sequence[dict[str, object]]
) -> list[dict[str, object]]:
    snr_by_file = {str(row["raw_file"]): row for row in snr_rows}
    grouped: dict[str, list[dict[str, object]]] = {}
    for paired in paired_rows:
        combined = dict(paired)
        combined["contrast_to_noise_ratio"] = snr_by_file[str(paired["raw_file"])].get(
            "snr_ratio"
        )
        grouped.setdefault(str(paired["titration_type"]), []).append(combined)
    output: list[dict[str, object]] = []
    for titration_type in sorted(grouped):
        rows = grouped[titration_type]
        ratios = [
            float(row["contrast_to_noise_ratio"])
            for row in rows
            if row["contrast_to_noise_ratio"] is not None
        ]
        improvements = [
            float(row["paired_ape_improvement_percentage_points"]) for row in rows
        ]
        output.append(
            {
                "titration_type": titration_type,
                "n_runs": len(rows),
                "valid_contrast_run_count": len(ratios),
                "median_contrast_to_noise_ratio": statistics.median(ratios) if ratios else None,
                "mean_ape_improvement_percentage_points": statistics.fmean(improvements),
                "fusion_better_run_count": sum(value > 0 for value in improvements),
                "fusion_worse_run_count": sum(value < 0 for value in improvements),
            }
        )
    return output


def model_stability_evidence(prediction_dir: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows: list[dict[str, object]] = []
    tree_path = prediction_dir / "fusion_tree_stability_probe.json"
    ensemble_path = prediction_dir / "modality_seed_ensemble_probe.json"
    if tree_path.is_file():
        payload = json.loads(tree_path.read_text(encoding="utf-8"))
        for item in payload.get("rows", []):
            rows.append(
                {
                    "probe": "fixed_selected_fusion_tree_seed",
                    "configuration": "fusion",
                    "seed": item.get("seed"),
                    "tree_multiplier": item.get("tree_multiplier"),
                    "mae_ml": item.get("mae_ml"),
                    "rmse_ml": item.get("rmse_ml"),
                    "mape_percent": item.get("mape_percent"),
                }
            )
    if ensemble_path.is_file():
        payload = json.loads(ensemble_path.read_text(encoding="utf-8"))
        for group, item in sorted(payload.get("groups", {}).items()):
            metrics = item.get("metrics", {})
            rows.append(
                {
                    "probe": "fixed_selected_probability_ensemble",
                    "configuration": group,
                    "seed": "+".join(str(seed) for seed in payload.get("seeds", [])),
                    "tree_multiplier": None,
                    "mae_ml": metrics.get("mae_ml"),
                    "rmse_ml": metrics.get("rmse_ml"),
                    "mape_percent": metrics.get("mape_percent"),
                }
            )
    fusion_seed_mapes = [
        float(row["mape_percent"])
        for row in rows
        if row["probe"] == "fixed_selected_fusion_tree_seed"
        and row["tree_multiplier"] == 1
        and row["mape_percent"] is not None
    ]
    summary = {
        "available": bool(rows),
        "source_files": [str(path) for path in (tree_path, ensemble_path) if path.is_file()],
        "fixed_selected_fusion_multiplier_1_mape_values_percent": fusion_seed_mapes,
        "fixed_selected_fusion_multiplier_1_mape_min_percent": min(fusion_seed_mapes)
        if fusion_seed_mapes
        else None,
        "fixed_selected_fusion_multiplier_1_mape_max_percent": max(fusion_seed_mapes)
        if fusion_seed_mapes
        else None,
        "interpretation": (
            "The selected development procedure is seed-sensitive; the 1.52% value is not "
            "a stable external-validation estimate. These probes do not reselect a model."
            if fusion_seed_mapes
            else "No stored seed-stability probe was available."
        ),
    }
    return rows, summary


def comparison_provenance(method_comparison_path: Path | None) -> dict[str, object]:
    if method_comparison_path is None or not method_comparison_path.is_file():
        return {"available": False}
    rows = read_csv(method_comparison_path)
    selected: dict[str, dict[str, object]] = {}
    for row in rows:
        selected[row["method"]] = {
            "family": row["family"],
            "mae_ml": finite_float(row["mae_ml"]),
            "rmse_ml": finite_float(row["rmse_ml"]),
            "mape_percent": finite_float(row["mape_percent"]),
        }
    return {
        "available": True,
        "source_file": str(method_comparison_path),
        "rows": selected,
        "manual_mape_percent": selected.get("수동 적정", {}).get("mape_percent"),
        "non_ml_color_slope_mape_percent": selected.get("색 최대 기울기", {}).get(
            "mape_percent"
        ),
        "non_ml_color_thermal_threshold_mape_percent": selected.get(
            "색·온도 임계값", {}
        ).get("mape_percent"),
        "stale_comparison_warning": (
            "Use this final comparison source. The older non_ml_baseline_comparison file "
            "contains a superseded manual row and a current-volume model excluded here."
        ),
    }


def write_plot(output_dir: Path, paired: Sequence[dict[str, object]]) -> str:
    labels = [str(row["run_id"]) for row in paired]
    color = [float(row["color_abs_error_ml"]) for row in paired]
    fusion = [float(row["fusion_abs_error_ml"]) for row in paired]
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        figure, axis = plt.subplots(figsize=(12, 6.75), dpi=200)
        positions = list(range(len(labels)))
        width = 0.38
        axis.bar([x - width / 2 for x in positions], color, width, label="Color only")
        axis.bar([x + width / 2 for x in positions], fusion, width, label="Color + thermal")
        axis.set_ylabel("Absolute endpoint error (mL)")
        axis.set_xlabel("Existing run")
        axis.set_title("Stored sensor-only predictions: paired endpoint errors")
        axis.set_xticks(positions, labels, rotation=45, ha="right")
        axis.legend()
        axis.grid(axis="y", alpha=0.25)
        figure.tight_layout()
        target = output_dir / "paired_endpoint_errors.png"
        figure.savefig(
            target,
            dpi=300,
            metadata={"Software": "analyze_existing_data_report_evidence.py"},
        )
        plt.close(figure)
        (output_dir / "paired_endpoint_errors.svg").unlink(missing_ok=True)
        return target.name
    except ImportError:
        width, height = 1600, 900
        margin_left, margin_bottom, margin_top, margin_right = 110, 150, 70, 40
        plot_width = width - margin_left - margin_right
        plot_height = height - margin_bottom - margin_top
        maximum = max(color + fusion + [1.0])
        group_width = plot_width / len(labels)
        bar_width = group_width * 0.32
        elements = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="white"/>',
            '<text x="800" y="38" text-anchor="middle" font-family="sans-serif" font-size="26">Stored sensor-only predictions: paired endpoint errors</text>',
            f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height-margin_bottom}" stroke="black"/>',
            f'<line x1="{margin_left}" y1="{height-margin_bottom}" x2="{width-margin_right}" y2="{height-margin_bottom}" stroke="black"/>',
        ]
        for index, label in enumerate(labels):
            center = margin_left + group_width * (index + 0.5)
            for offset, value, fill in ((-bar_width, color[index], "#4c78a8"), (0, fusion[index], "#f58518")):
                bar_height = value / maximum * plot_height
                elements.append(
                    f'<rect x="{center+offset:.3f}" y="{height-margin_bottom-bar_height:.3f}" width="{bar_width:.3f}" height="{bar_height:.3f}" fill="{fill}"/>'
                )
            elements.append(
                f'<text x="{center:.3f}" y="{height-margin_bottom+28}" text-anchor="middle" font-family="sans-serif" font-size="15">{label}</text>'
            )
        elements.extend(
            [
                '<rect x="1130" y="65" width="22" height="22" fill="#4c78a8"/><text x="1162" y="83" font-family="sans-serif" font-size="18">Color only</text>',
                '<rect x="1300" y="65" width="22" height="22" fill="#f58518"/><text x="1332" y="83" font-family="sans-serif" font-size="18">Color + thermal</text>',
                "</svg>\n",
            ]
        )
        target = output_dir / "paired_endpoint_errors.svg"
        target.write_text("\n".join(elements), encoding="utf-8")
        (output_dir / "paired_endpoint_errors.png").unlink(missing_ok=True)
        return target.name


def write_thermal_plots(
    output_dir: Path,
    snr_rows: Sequence[dict[str, object]],
    paired: Sequence[dict[str, object]],
) -> list[str]:
    """Write print-scale figures; return an empty list only without matplotlib."""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []

    labels = [str(row["run_id"]) for row in snr_rows]
    ratios = [float(row["snr_ratio"]) if row["snr_ratio"] is not None else math.nan for row in snr_rows]
    figure, axis = plt.subplots(figsize=(12, 6.75), dpi=200)
    positions = list(range(len(labels)))
    colors = ["#2563eb" if math.isfinite(value) else "#94a3b8" for value in ratios]
    axis.bar(positions, [value if math.isfinite(value) else 0.0 for value in ratios], color=colors)
    axis.set_ylabel("Operational contrast-to-noise ratio")
    axis.set_xlabel("Existing run")
    axis.set_title("Endpoint-to-baseline thermal contrast (robust MAD noise)")
    axis.set_xticks(positions, labels, rotation=45, ha="right")
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    contrast_target = output_dir / "thermal_contrast_by_run.png"
    figure.savefig(
        contrast_target,
        dpi=300,
        metadata={"Software": "analyze_existing_data_report_evidence.py"},
    )
    plt.close(figure)

    snr_by_file = {str(row["raw_file"]): row for row in snr_rows}
    points = [
        (
            float(snr_by_file[str(row["raw_file"])]["snr_ratio"]),
            float(row["paired_ape_improvement_percentage_points"]),
            str(row["run_id"]),
        )
        for row in paired
        if snr_by_file[str(row["raw_file"])]["snr_ratio"] is not None
    ]
    figure, axis = plt.subplots(figsize=(12, 6.75), dpi=200)
    axis.axhline(0.0, color="#475569", linewidth=1.0, linestyle="--")
    axis.scatter([point[0] for point in points], [point[1] for point in points], color="#f97316")
    for x_value, y_value, label in points:
        axis.annotate(label, (x_value, y_value), xytext=(4, 4), textcoords="offset points", fontsize=8)
    axis.set_xlabel("Operational thermal contrast-to-noise ratio")
    axis.set_ylabel("Color − fusion APE (percentage points)")
    axis.set_title("Exploratory thermal contrast versus fusion error change")
    axis.grid(alpha=0.25)
    figure.tight_layout()
    correlation_target = output_dir / "thermal_contrast_vs_fusion_improvement.png"
    figure.savefig(
        correlation_target,
        dpi=300,
        metadata={"Software": "analyze_existing_data_report_evidence.py"},
    )
    plt.close(figure)
    return [contrast_target.name, correlation_target.name]


def markdown_report(
    summary: dict[str, object], plot_name: str, thermal_plot_names: Sequence[str]
) -> str:
    paired = summary["paired_color_vs_fusion"]
    metrics = summary["reproduced_prediction_metrics"]
    snr_counts = summary["thermal_snr_status_counts"]
    lines = [
        "# Existing-data report evidence (no new wet experiment)",
        "",
        "This is a deterministic secondary analysis of existing files. It is **not independent validation**, and no new experimental observations were generated.",
        "",
        "## Data inventory",
        "",
        f"- Raw runs: **{summary['raw_run_count']}**",
        f"- Raw rows: **{summary['raw_row_count']}**",
        "- Every raw file is identified by SHA-256 in `raw_inventory.csv`.",
        "- For the weak-acid/weak-base runs, the research participant later reported `bromothymol_blue (BTB)`, while the retained raw metadata says `methyl_orange`. No contemporaneous run-linked primary record was identified, so BTB is recorded only as a participant-reported, not independently verified correction; raw files remain unchanged and hashed.",
        "",
        "## Frozen operational thermal contrast method",
        "",
        f"Before interpreting results, the primary rule is fixed as follows: baseline rows have normalized volume {BASELINE_START_FRACTION:.2f} ≤ V/V_eq ≤ {BASELINE_END_FRACTION:.2f}; endpoint rows have {ENDPOINT_START_FRACTION:.2f} ≤ V/V_eq ≤ {ENDPOINT_END_FRACTION:.2f}. Signed signal is median(endpoint) − median(baseline), noise is 1.4826 × MAD(baseline), and the operational contrast-to-noise ratio is |signal|/noise. This is not an instrument S/N measurement.",
        "",
        f"Rows whose available ROI summary fields are all zero are excluded as internally invalid records. A result fails if baseline n < {MIN_BASELINE_SAMPLES}, endpoint n < {MIN_ENDPOINT_SAMPLES}, or scaled MAD ≤ {NEAR_ZERO_NOISE_C:g} °C. Fixed endpoint windows ±0.5, ±1.0, and ±2.0 mL are reported as sensitivity analyses.",
        "",
        "Status counts: " + ", ".join(f"`{key}`={value}" for key, value in sorted(snr_counts.items())) + ".",
        "",
        "## Stored prediction metrics reproduced from prediction rows",
        "",
        "| Modality | n | MAE (mL) | RMSE (mL) | MAPE (%) |",
        "|---|---:|---:|---:|---:|",
    ]
    for modality in MODALITY_FILES:
        item = metrics[modality]
        lines.append(
            f"| {modality} | {item['n_runs']} | {item['mae_ml']:.6f} | {item['rmse_ml']:.6f} | {item['mape_percent']:.6f} |"
        )
    lines.extend(
        [
            "",
            "Metrics were recomputed from actual and predicted endpoint volumes; stored aggregate/error columns were not treated as authoritative.",
            "",
            "## Paired color-only versus fusion comparison",
            "",
            f"The sole primary paired estimand is `color APE − fusion APE` in percentage points, so positive values favor fusion. Mean improvement: **{paired['mean_ape_improvement_percentage_points']:.6f} percentage points**. Reaction-type-stratified paired-run bootstrap 95% percentile CI: **[{paired['stratified_bootstrap_95_ci_low_percentage_points']:.6f}, {paired['stratified_bootstrap_95_ci_high_percentage_points']:.6f}]** ({paired['bootstrap_replicates']} replicates, seed {paired['bootstrap_seed']}). Exact two-sided sign-flip p-value: **{paired['exact_sign_flip_two_sided_p_value']:.6f}**; exact sign-test p-value: **{paired['exact_sign_test_two_sided_p_value']:.6f}**.",
            "",
            f"Fusion improved {paired['fusion_better_run_count']}/12 runs and degraded {paired['fusion_worse_run_count']}/12. Because the interval crosses zero and both exact tests are non-significant, the current data do not establish fusion superiority, equivalence, universal benefit, conditional benefit, or external validity. These intervals are conditional on already selected post-hoc models and do not include model-selection uncertainty.",
            "",
            f"![Paired endpoint errors]({plot_name})",
            "",
        ]
    )
    if thermal_plot_names:
        lines.extend(
            [
                "## Exploratory thermal relationship",
                "",
                f"Primary-window Spearman ρ={summary['thermal_contrast_vs_fusion_improvement']['primary_spearman_rho']:.6f}; fixed-seed exploratory permutation p={summary['thermal_contrast_vs_fusion_improvement']['primary_unadjusted_permutation_p_value']:.6f}. This analysis is exploratory, unadjusted, and not evidence that thermal contrast predicts model improvement.",
                "",
                f"![Thermal contrast by run]({thermal_plot_names[0]})",
                "",
                f"![Thermal contrast versus fusion improvement]({thermal_plot_names[1]})",
                "",
            ]
        )
    lines.extend(
        [
            "## Stability and claim limits",
            "",
            summary["model_stability"]["interpretation"],
            "",
            "Claim rules are encoded in `summary.json`: superiority requires a favorable CI excluding zero and a corrected/sign-based test pass; equivalence requires a predeclared equivalence margin and a fully contained CI; universal benefit fails when any run degrades. None of those stronger claims pass here.",
            "",
        ]
    )
    return "\n".join(lines)


def analyze(
    raw_dir: Path,
    prediction_dir: Path,
    output_dir: Path,
    *,
    expected_runs: int | None = 12,
    expected_rows: int | None = 1822,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    bootstrap_replicates: int = BOOTSTRAP_REPLICATES,
    correlation_permutation_seed: int = CORRELATION_PERMUTATION_SEED,
    correlation_permutations: int = CORRELATION_PERMUTATIONS,
    method_comparison_path: Path | None = None,
) -> dict[str, object]:
    inventory, rows_by_file = inventory_raw_runs(raw_dir)
    raw_rows = sum(int(row["row_count"]) for row in inventory)
    if expected_runs is not None and len(inventory) != expected_runs:
        raise ValueError(f"expected {expected_runs} raw runs, found {len(inventory)}")
    if expected_rows is not None and raw_rows != expected_rows:
        raise ValueError(f"expected {expected_rows} raw rows, found {raw_rows}")

    predictions = {
        modality: prediction_rows(prediction_dir / filename)
        for modality, filename in MODALITY_FILES.items()
    }
    expected_files = {str(row["raw_file"]) for row in inventory}
    for modality, modality_predictions in predictions.items():
        if set(modality_predictions) != expected_files:
            raise ValueError(f"{modality} predictions do not match raw run inventory")

    snr_rows = [
        thermal_snr_for_run(row, rows_by_file[str(row["raw_file"])]) for row in inventory
    ]
    sensitivity_rows = [
        sensitivity
        for row in inventory
        for sensitivity in thermal_sensitivity_rows(
            row, rows_by_file[str(row["raw_file"])]
        )
    ]
    metrics_rows: list[dict[str, object]] = []
    metrics_summary: dict[str, dict[str, float | int]] = {}
    for modality in MODALITY_FILES:
        values = error_metrics(predictions[modality].values())
        metrics_summary[modality] = values
        metrics_rows.append({"modality": modality, **values})
    paired = paired_error_rows(
        inventory, predictions["color_only"], predictions["color_thermal_fusion"]
    )
    ml_improvements = [float(row["paired_improvement_ml"]) for row in paired]
    ape_improvements = [
        float(row["paired_ape_improvement_percentage_points"]) for row in paired
    ]
    ordinary_ape_ci_low, ordinary_ape_ci_high = paired_bootstrap_ci(
        ape_improvements, seed=bootstrap_seed, replicates=bootstrap_replicates
    )
    stratified_ape_ci_low, stratified_ape_ci_high = stratified_paired_bootstrap_ci(
        paired,
        value_field="paired_ape_improvement_percentage_points",
        seed=bootstrap_seed,
        replicates=bootstrap_replicates,
    )
    stratified_ml_ci_low, stratified_ml_ci_high = stratified_paired_bootstrap_ci(
        paired,
        value_field="paired_improvement_ml",
        seed=bootstrap_seed + 1,
        replicates=bootstrap_replicates,
    )
    status_counts: dict[str, int] = {}
    for row in snr_rows:
        status = str(row["snr_status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    sign_flip_p = exact_sign_flip_p_value(ape_improvements)
    sign_test_p = exact_sign_test_p_value(ape_improvements)
    paired_summary: dict[str, object] = {
        "n_runs": len(paired),
        "primary_estimand": "mean(color APE - fusion APE), percentage points",
        "mean_ape_improvement_percentage_points": statistics.fmean(ape_improvements),
        "median_ape_improvement_percentage_points": statistics.median(ape_improvements),
        "mean_improvement_ml": statistics.fmean(ml_improvements),
        "median_improvement_ml": statistics.median(ml_improvements),
        "fusion_better_run_count": sum(value > 0 for value in ape_improvements),
        "fusion_worse_run_count": sum(value < 0 for value in ape_improvements),
        "fusion_tied_run_count": sum(abs(value) <= 1e-15 for value in ape_improvements),
        "bootstrap_method": "reaction_type_stratified_paired_run_percentile",
        "bootstrap_unit": "run (frames are never resampled)",
        "bootstrap_seed": bootstrap_seed,
        "bootstrap_replicates": bootstrap_replicates,
        "stratified_bootstrap_95_ci_low_percentage_points": stratified_ape_ci_low,
        "stratified_bootstrap_95_ci_high_percentage_points": stratified_ape_ci_high,
        "ordinary_bootstrap_sensitivity_95_ci_low_percentage_points": ordinary_ape_ci_low,
        "ordinary_bootstrap_sensitivity_95_ci_high_percentage_points": ordinary_ape_ci_high,
        "stratified_bootstrap_95_ci_low_ml": stratified_ml_ci_low,
        "stratified_bootstrap_95_ci_high_ml": stratified_ml_ci_high,
        "sign_flip_test": "exact_two_sided_absolute_mean_APE_improvement",
        "sign_flip_assumption": (
            "Symmetry/exchangeability is not design-based for these retrospective runs."
        ),
        "sign_flip_assignments": 2 ** len(ape_improvements),
        "exact_sign_flip_two_sided_p_value": sign_flip_p,
        "exact_sign_test_two_sided_p_value": sign_test_p,
        "conditional_on_selected_models": True,
        "accounts_for_model_selection_optimism": False,
    }
    snr_by_file = {str(row["raw_file"]): row for row in snr_rows}
    correlation_pairs = [
        (
            float(snr_by_file[str(row["raw_file"])]["snr_ratio"]),
            float(row["paired_ape_improvement_percentage_points"]),
        )
        for row in paired
        if snr_by_file[str(row["raw_file"])]["snr_ratio"] is not None
    ]
    primary_rho, primary_correlation_p = spearman_permutation_p_value(
        [pair[0] for pair in correlation_pairs],
        [pair[1] for pair in correlation_pairs],
        seed=correlation_permutation_seed,
        permutations=correlation_permutations,
    )
    paired_improvement_by_file = {
        str(row["raw_file"]): float(row["paired_ape_improvement_percentage_points"])
        for row in paired
    }
    sensitivity_correlations: dict[str, float | None] = {}
    for window_name in sorted({str(row["window_name"]) for row in sensitivity_rows}):
        window_rows = [
            row
            for row in sensitivity_rows
            if row["window_name"] == window_name
            and row["contrast_to_noise_ratio"] is not None
        ]
        if len(window_rows) < 2:
            sensitivity_correlations[window_name] = None
            continue
        sensitivity_correlations[window_name] = spearman_correlation(
            [float(row["contrast_to_noise_ratio"]) for row in window_rows],
            [paired_improvement_by_file[str(row["raw_file"])] for row in window_rows],
        )
    stability_rows, stability_summary = model_stability_evidence(prediction_dir)
    type_summaries = reaction_type_summaries(snr_rows, paired)
    universal_benefit_pass = paired_summary["fusion_worse_run_count"] == 0
    superiority_pass = (
        stratified_ape_ci_low > 0 and sign_flip_p < 0.05 and sign_test_p < 0.05
    )
    summary: dict[str, object] = {
        "analysis_scope": "existing_data_only_no_new_wet_experiment",
        "independent_validation": False,
        "raw_run_count": len(inventory),
        "raw_row_count": raw_rows,
        "thermal_contrast_method": {
            "name": "operational endpoint-to-baseline contrast-to-noise ratio",
            "not_instrument_snr": True,
            "measurement": "thermal_roi_avg",
            "baseline_volume_interval": "0.05 <= injected_volume_ml / theoretical_equivalence_volume_ml <= 0.20",
            "primary_endpoint_interval": "0.95 <= injected_volume_ml / theoretical_equivalence_volume_ml <= 1.05",
            "fixed_width_sensitivity_half_widths_ml": list(FIXED_ENDPOINT_HALF_WIDTHS_ML),
            "signal": "median(endpoint) - median(baseline); signed value retained",
            "noise": "1.4826 * median(abs(baseline - median(baseline)))",
            "ratio": "abs(signal) / noise",
            "decibels": "20 * log10(ratio)",
            "near_zero_noise_threshold_c": NEAR_ZERO_NOISE_C,
            "minimum_baseline_samples": MIN_BASELINE_SAMPLES,
            "minimum_endpoint_samples": MIN_ENDPOINT_SAMPLES,
            "invalid_row_rule": (
                "exclude a row only when thermal_roi_avg is zero and every available "
                "ROI summary among avg/min/max/std is also zero"
            ),
        },
        "thermal_snr_status_counts": status_counts,
        "invalid_all_zero_thermal_row_count": sum(
            int(row["invalid_all_zero_thermal_rows"]) for row in snr_rows
        ),
        "indicator_correction": {
            "applies_to_titration_type": "weak_acid_weak_base",
            "raw_recorded_indicator": "methyl_orange",
            "participant_reported_indicator": "bromothymol_blue (BTB)",
            "evidence_status": "participant_reported_not_independently_verified",
            "run_linked_primary_record_available": False,
            "source_handling": "raw CSVs unchanged; participant report recorded in derived inventory",
            "validation_limit": "no contemporaneous run-linked primary record found; not independently revalidated by this analysis",
        },
        "reproduced_prediction_metrics": metrics_summary,
        "paired_color_vs_fusion": paired_summary,
        "thermal_contrast_vs_fusion_improvement": {
            "status": "exploratory_not_primary",
            "n_runs": len(correlation_pairs),
            "primary_spearman_rho": primary_rho,
            "primary_unadjusted_permutation_p_value": primary_correlation_p,
            "permutation_seed": correlation_permutation_seed,
            "permutations": correlation_permutations,
            "window_sensitivity_spearman_rho": sensitivity_correlations,
            "supports_predictive_claim": False,
        },
        "reaction_type_summaries": type_summaries,
        "model_stability": stability_summary,
        "comparison_provenance": comparison_provenance(method_comparison_path),
        "selection_validity": {
            "stored_analysis_type": "post_hoc_typewise_development_selection_not_nested_validation",
            "loro_fit_excludes_each_test_run": True,
            "candidate_selection_uses_all_three_loro_errors_within_each_type": True,
            "independent_external_validation": False,
            "bootstrap_removes_selection_optimism": False,
        },
        "multiplicity_hierarchy": {
            "sole_primary_comparison": "color-only versus color+thermal fusion APE",
            "exploratory_only": [
                "thermal-only metrics",
                "thermal contrast correlation",
                "reaction-type summaries",
            ],
            "typewise_tests_performed": False,
            "holm_required": False,
            "reason": "Only one paired inferential comparison is designated primary.",
        },
        "claim_fail_rules": {
            "fusion_improves_color": {
                "pass": superiority_pass,
                "rule": "stratified CI entirely above zero and both exact tests p<0.05",
            },
            "fusion_equivalent_to_color": {
                "pass": False,
                "rule": "no equivalence margin was predeclared; equivalence is not claimed",
            },
            "universal_thermal_benefit": {
                "pass": universal_benefit_pass,
                "rule": "fails when any paired run degrades",
            },
            "conditional_thermal_benefit": {
                "pass": False,
                "rule": "requires an outcome-independent condition and interaction evidence; n=3/type is inadequate",
            },
            "thermal_contrast_predicts_improvement": {
                "pass": False,
                "rule": "exploratory unadjusted relationship is insufficient and must be window-stable",
            },
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "raw_inventory.csv", inventory, INVENTORY_FIELDS)
    write_csv(output_dir / "thermal_snr_by_run.csv", snr_rows, SNR_FIELDS)
    write_csv(output_dir / "thermal_contrast_by_run.csv", snr_rows, SNR_FIELDS)
    write_csv(
        output_dir / "thermal_contrast_window_sensitivity.csv",
        sensitivity_rows,
        SENSITIVITY_FIELDS,
    )
    write_csv(output_dir / "color_vs_fusion_paired_errors.csv", paired, PAIRED_FIELDS)
    write_csv(output_dir / "reproduced_modality_metrics.csv", metrics_rows, METRIC_FIELDS)
    write_csv(output_dir / "reaction_type_summary.csv", type_summaries, TYPE_SUMMARY_FIELDS)
    write_csv(output_dir / "model_stability_summary.csv", stability_rows, STABILITY_FIELDS)
    plot_name = write_plot(output_dir, paired)
    thermal_plot_names = write_thermal_plots(output_dir, snr_rows, paired)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(
        markdown_report(summary, plot_name, thermal_plot_names), encoding="utf-8"
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("머신러닝용 파일모음"))
    parser.add_argument(
        "--prediction-dir",
        type=Path,
        default=Path("data/ml/report_modality_sensor_features_only"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/analysis/report_evidence_no_new_wet"),
    )
    parser.add_argument("--expected-runs", type=int, default=12)
    parser.add_argument("--expected-rows", type=int, default=1822)
    parser.add_argument("--bootstrap-seed", type=int, default=BOOTSTRAP_SEED)
    parser.add_argument("--bootstrap-replicates", type=int, default=BOOTSTRAP_REPLICATES)
    parser.add_argument(
        "--correlation-permutation-seed", type=int, default=CORRELATION_PERMUTATION_SEED
    )
    parser.add_argument(
        "--correlation-permutations", type=int, default=CORRELATION_PERMUTATIONS
    )
    parser.add_argument(
        "--method-comparison-path",
        type=Path,
        default=Path("docs/report_revision_figures/source_data/method_comparison.csv"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = analyze(
        args.raw_dir,
        args.prediction_dir,
        args.output_dir,
        expected_runs=args.expected_runs,
        expected_rows=args.expected_rows,
        bootstrap_seed=args.bootstrap_seed,
        bootstrap_replicates=args.bootstrap_replicates,
        correlation_permutation_seed=args.correlation_permutation_seed,
        correlation_permutations=args.correlation_permutations,
        method_comparison_path=args.method_comparison_path,
    )
    print(
        f"wrote existing-data evidence for {summary['raw_run_count']} runs / "
        f"{summary['raw_row_count']} rows to {args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
