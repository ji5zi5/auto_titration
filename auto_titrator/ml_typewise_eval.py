"""Typewise ML evaluation for equivalence-zone analysis.

This module is deliberately separate from :mod:`auto_titrator.ml_train`.
The older trainer has a broad default feature list that includes columns that
are unsafe for this task.  Here, theoretical equivalence data is used only for
label generation/evaluation; a dedicated denylist protects model inputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .chemistry import SUPPORTED_TITRATION_TYPES
from .ml_features import DERIVED_ML_COLUMNS, derive_ml_features

RANDOM_STATE = 42
OBSERVATION_UNIT = "frame_level_observations_not_independent_experiments"
FEATURE_SETS = ("color", "thermal", "sensor_fusion", "full")


@dataclass(frozen=True)
class CsvRun:
    path: Path
    titration_type: str
    concentration_m: float
    theoretical_equivalence_volume_ml: float
    rows: list[dict[str, Any]]


@dataclass(frozen=True)
class TypewiseFold:
    titration_type: str
    held_out_concentration_m: float
    train_runs: list[CsvRun]
    test_runs: list[CsvRun]


FORBIDDEN_COLUMNS = {
    "theoretical_equivalence_volume_ml",
    "theoretical_equivalence_time_s",
    "theoretical_equivalence_pH",
    "distance_to_equivalence_ml",
    "time_to_equivalence_s",
    "equivalence_window_ml",
    "equivalence_window_label",
    "status_label",
    "status_confidence",
    "indicator_endpoint_volume_ml",
    "indicator_endpoint_offset_ml",
    "indicator_endpoint_confidence",
    "indicator_endpoint_warning",
    "estimated_equivalence_volume_ml",
    "estimated_equivalence_time_s",
    "absolute_volume_error_ml",
    "relative_volume_error_percent",
    "candidate_index",
    "csv_session_id",
    "csv_row_index",
    "roi_session_id",
    "frame_id",
    "sample_concentration_M",
    "delta_ml",
    "zone_label",
}

FORBIDDEN_SUFFIXES = ("_label", "_target")
FORBIDDEN_PREFIXES = (
    "reference_",
    "actual_",
    "predicted_",
    "estimated_equivalence_",
)
FORBIDDEN_CONTAINS = ("equivalence",)

RAW_TIMELINE_COLUMNS = {
    "time_s",
    "csv_recording_elapsed_s",
    "pump_elapsed_s",
    "injected_volume_ml",
    "pump_run_rate_ml_per_s",
    "confirmed_injected_volume_ml",
    "commanded_volume_ml",
}

STATIC_METADATA_COLUMNS = {
    "titration_type",
    "sample_name",
    "sample_volume_ml",
    "sample_valence",
    "titrant_name",
    "titrant_concentration_M",
    "titrant_valence",
    "indicator",
    "selected_pka_value",
    "selected_pka_type",
    "thermal_source",
    "thermal_conversion_model",
    "thermal_calibrated",
    "theoretical_equivalence_volume_ml",
}

VISIBLE_PREFIXES = ("visible_",)
THERMAL_PREFIXES = ("thermal_",)
PUMP_PREFIXES = ("pump_",)
QUALITY_FEATURES = {"abs_sync_offset_ms", "training_quality_score", "valid_for_training"}


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _first_numeric(rows: Sequence[Mapping[str, Any]], column: str) -> float | None:
    for row in rows:
        value = _to_float(row.get(column))
        if value is not None:
            return value
    return None


def _first_text(rows: Sequence[Mapping[str, Any]], column: str) -> str:
    for row in rows:
        text = str(row.get(column) or "").strip()
        if text:
            return text
    return ""


def load_runs(folder: str | Path) -> list[CsvRun]:
    """Load experiment CSVs from a folder."""

    root = Path(folder)
    if not root.exists():
        raise FileNotFoundError(f"CSV folder does not exist: {root}")
    runs: list[CsvRun] = []
    for path in sorted(root.glob("*.csv")):
        with path.open(newline="", encoding="utf-8-sig") as fh:
            rows = [dict(row) for row in csv.DictReader(fh)]
        if not rows:
            continue
        titration_type = _first_text(rows, "titration_type")
        if titration_type not in SUPPORTED_TITRATION_TYPES:
            raise ValueError(f"{path}: unsupported or missing titration_type={titration_type!r}")
        concentration = _first_numeric(rows, "sample_concentration_M")
        if concentration is None:
            concentration = _infer_concentration_from_name(path.name)
        if concentration is None:
            raise ValueError(f"{path}: missing sample_concentration_M")
        theoretical_volume = _first_numeric(rows, "theoretical_equivalence_volume_ml")
        if theoretical_volume is None:
            raise ValueError(f"{path}: missing theoretical_equivalence_volume_ml")
        if _first_numeric(rows, "time_s") is None:
            raise ValueError(f"{path}: missing time_s")
        if _first_numeric(rows, "injected_volume_ml") is None:
            raise ValueError(f"{path}: missing injected_volume_ml")
        runs.append(
            CsvRun(
                path=path,
                titration_type=titration_type,
                concentration_m=float(concentration),
                theoretical_equivalence_volume_ml=float(theoretical_volume),
                rows=rows,
            )
        )
    return runs


def _infer_concentration_from_name(name: str) -> float | None:
    match = re.search(r"(?<!\\d)(0\\.\\d+|\\d+(?:\\.\\d+)?)\\s*(?:m|M)?", name)
    return float(match.group(1)) if match else None


def _is_raw_numeric_column(column: str) -> bool:
    if column in RAW_TIMELINE_COLUMNS:
        return True
    if column in DERIVED_ML_COLUMNS:
        return False
    if is_forbidden_feature(column):
        return False
    if column.startswith(VISIBLE_PREFIXES) or column.startswith(THERMAL_PREFIXES):
        return True
    return column.startswith(PUMP_PREFIXES) and column in RAW_TIMELINE_COLUMNS


def resample_run(run: CsvRun, *, fps: float = 25.0, window_ml: float = 0.5) -> CsvRun:
    """Return a resampled view of a run.

    Only raw observables/timeline values are interpolated. Labels and derived
    features are recreated afterward.
    """

    if fps <= 0:
        raise ValueError("fps must be positive")

    timed: list[tuple[float, dict[str, Any]]] = []
    seen: set[float] = set()
    for row in run.rows:
        time_value = _to_float(row.get("time_s"))
        if time_value is None or time_value in seen:
            continue
        seen.add(time_value)
        timed.append((time_value, row))
    timed.sort(key=lambda item: item[0])
    if not timed:
        raise ValueError(f"{run.path}: no numeric time_s rows")

    times = np.array([item[0] for item in timed], dtype=float)
    rows = [item[1] for item in timed]
    start = float(times[0])
    end = float(times[-1])
    dt = 1.0 / float(fps)
    if end <= start:
        grid = np.array([start], dtype=float)
    else:
        count = int(math.floor((end - start) / dt)) + 1
        grid = start + np.arange(count, dtype=float) * dt
        if grid[-1] < end and (end - grid[-1]) > dt * 0.5:
            grid = np.append(grid, end)

    all_columns = set().union(*(row.keys() for row in rows))
    numeric_columns = sorted(column for column in all_columns if _is_raw_numeric_column(column))
    static_columns = sorted(column for column in all_columns if column in STATIC_METADATA_COLUMNS)

    series: dict[str, np.ndarray] = {}
    for column in numeric_columns:
        pairs = [(time_value, _to_float(row.get(column))) for time_value, row in timed]
        valid = [(time_value, value) for time_value, value in pairs if value is not None]
        if not valid:
            continue
        x = np.array([item[0] for item in valid], dtype=float)
        y = np.array([item[1] for item in valid], dtype=float)
        series[column] = np.interp(grid, x, y)

    metadata = {column: _first_text(rows, column) for column in static_columns}
    metadata["titration_type"] = run.titration_type
    metadata["sample_concentration_M"] = str(run.concentration_m)
    metadata["theoretical_equivalence_volume_ml"] = str(run.theoretical_equivalence_volume_ml)

    resampled_rows: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    for index, time_value in enumerate(grid):
        row: dict[str, Any] = dict(metadata)
        row["time_s"] = round(float(time_value), 6)
        for column, values in series.items():
            row[column] = round(float(values[index]), 6)
        row.update(derive_ml_features(history, row))
        history.append(dict(row))
        resampled_rows.append(row)

    resampled_rows = generate_labels(resampled_rows, window_ml=window_ml)
    return CsvRun(
        path=run.path,
        titration_type=run.titration_type,
        concentration_m=run.concentration_m,
        theoretical_equivalence_volume_ml=run.theoretical_equivalence_volume_ml,
        rows=resampled_rows,
    )


def generate_labels(rows: Sequence[Mapping[str, Any]], *, window_ml: float = 0.5) -> list[dict[str, Any]]:
    labeled: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        injected = _to_float(row.get("injected_volume_ml"))
        theoretical = _to_float(row.get("theoretical_equivalence_volume_ml"))
        if injected is None or theoretical is None:
            raise ValueError("label generation requires injected_volume_ml and theoretical_equivalence_volume_ml")
        delta = injected - theoretical
        row["delta_ml"] = round(delta, 6)
        row["zone_label"] = zone_for_delta(delta, window_ml=window_ml)
        labeled.append(row)
    return labeled


def zone_for_delta(delta_ml: float, *, window_ml: float = 0.5) -> str:
    window = abs(float(window_ml))
    if delta_ml < -(2.0 * window):
        return "far_before"
    if delta_ml < -window:
        return "approaching"
    if delta_ml <= window:
        return "equivalence_zone"
    if delta_ml <= 2.0 * window:
        return "after"
    return "overshoot"


def is_forbidden_feature(column: str) -> bool:
    name = str(column)
    if name in FORBIDDEN_COLUMNS:
        return True
    if name.startswith("titration_is_"):
        return True
    if any(name.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        return True
    if any(name.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
        return True
    if any(part in name for part in FORBIDDEN_CONTAINS):
        return True
    return False


def forbidden_features(columns: Iterable[str]) -> list[str]:
    return [column for column in columns if is_forbidden_feature(column)]


def assert_no_forbidden_features(columns: Iterable[str]) -> None:
    blocked = forbidden_features(columns)
    if blocked:
        raise ValueError(f"forbidden model feature(s): {', '.join(blocked)}")


def select_feature_columns(columns: Iterable[str], *, feature_set: str = "full") -> list[str]:
    selected: list[str] = []
    for column in sorted(set(columns)):
        if is_forbidden_feature(column):
            continue
        if column in {"titration_type", "sample_name", "titrant_name", "indicator"}:
            continue
        if feature_set == "color" and not column.startswith(VISIBLE_PREFIXES):
            continue
        if feature_set == "thermal" and not column.startswith(THERMAL_PREFIXES):
            continue
        if feature_set == "sensor_fusion" and not (
            column.startswith(VISIBLE_PREFIXES) or column.startswith(THERMAL_PREFIXES)
        ):
            continue
        if feature_set == "full" and not _is_allowed_full_feature(column):
            continue
        selected.append(column)
    return selected


def _is_allowed_full_feature(column: str) -> bool:
    if column in {"time_s", "injected_volume_ml", "pump_run_rate_ml_per_s", "titrant_concentration_M", "sample_volume_ml"}:
        return True
    if column in QUALITY_FEATURES:
        return True
    if column in DERIVED_ML_COLUMNS and not column.startswith("titration_is_"):
        return True
    return column.startswith(VISIBLE_PREFIXES) or column.startswith(THERMAL_PREFIXES)


def build_typewise_folds(runs: Sequence[CsvRun]) -> list[TypewiseFold]:
    by_type: dict[str, list[CsvRun]] = defaultdict(list)
    for run in runs:
        by_type[run.titration_type].append(run)

    folds: list[TypewiseFold] = []
    for titration_type in sorted(by_type):
        type_runs = by_type[titration_type]
        concentrations = sorted({round(run.concentration_m, 8) for run in type_runs})
        for concentration in concentrations:
            train = [run for run in type_runs if round(run.concentration_m, 8) != concentration]
            test = [run for run in type_runs if round(run.concentration_m, 8) == concentration]
            if train and test:
                folds.append(TypewiseFold(titration_type, float(concentration), train, test))
    return folds


def _rows_for_runs(runs: Sequence[CsvRun]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for run in runs:
        for row in run.rows:
            out = dict(row)
            out["_run_path"] = str(run.path)
            out["_concentration_m"] = run.concentration_m
            result.append(out)
    return result


def _matrix(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> list[list[float]]:
    matrix: list[list[float]] = []
    for row in rows:
        matrix.append([_to_float(row.get(column)) or 0.0 for column in columns])
    return matrix


class MajorityClassifier:
    name = "majority_baseline"

    def fit(self, labels: Sequence[str]) -> None:
        self.label = Counter(labels).most_common(1)[0][0] if labels else "far_before"

    def predict(self, n: int) -> list[str]:
        return [self.label for _ in range(n)]

    def metadata(self) -> dict[str, Any]:
        return {"model_family": self.name, "hyperparameters": {}, "scaler": None, "imputer": "zero_fill"}


class MedianRegressor:
    name = "median_baseline"

    def fit(self, values: Sequence[float]) -> None:
        self.value = float(statistics.median(values)) if values else 0.0

    def predict(self, n: int) -> list[float]:
        return [self.value for _ in range(n)]

    def metadata(self) -> dict[str, Any]:
        return {"model_family": self.name, "hyperparameters": {}, "scaler": None, "imputer": "zero_fill"}


def _sklearn_versions() -> dict[str, str | None]:
    try:
        import sklearn  # type: ignore

        sklearn_version = sklearn.__version__
    except Exception:
        sklearn_version = None
    return {"sklearn_version": sklearn_version, "numpy_version": np.__version__, "python_version": platform.python_version()}


def _candidate_predictions(
    train_rows: Sequence[Mapping[str, Any]],
    test_rows: Sequence[Mapping[str, Any]],
    feature_columns: Sequence[str],
    *,
    quick: bool,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    y_class = [str(row["zone_label"]) for row in train_rows]
    y_reg = [float(row["delta_ml"]) for row in train_rows]
    actual_class = [str(row["zone_label"]) for row in test_rows]
    actual_reg = [float(row["delta_ml"]) for row in test_rows]

    classifier = MajorityClassifier()
    classifier.fit(y_class)
    class_pred = classifier.predict(len(test_rows))
    regressor = MedianRegressor()
    regressor.fit(y_reg)
    reg_pred = regressor.predict(len(test_rows))

    class_candidates = [_classification_result(classifier.name, class_pred, actual_class, classifier.metadata())]
    reg_candidates = [_regression_result(regressor.name, reg_pred, actual_reg, regressor.metadata())]
    failures: list[dict[str, Any]] = []

    if not quick:
        sk_class, sk_reg, sk_failures, sklearn_available = _try_sklearn_candidates(
            train_rows, test_rows, feature_columns, actual_class, actual_reg
        )
        class_candidates.extend(sk_class)
        reg_candidates.extend(sk_reg)
        failures.extend(sk_failures)
        if sklearn_available and (len(class_candidates) < 3 or len(reg_candidates) < 3):
            raise RuntimeError(
                "scikit-learn is available but fewer than 3 classifier/regressor families ran; "
                f"classifiers={len(class_candidates)} regressors={len(reg_candidates)} failures={failures}"
            )
    class_result = max(class_candidates, key=lambda result: result["accuracy"])
    reg_result = min(reg_candidates, key=lambda result: result["mae"])
    return class_result, reg_result, class_candidates, reg_candidates, failures


def _try_sklearn_candidates(
    train_rows: Sequence[Mapping[str, Any]],
    test_rows: Sequence[Mapping[str, Any]],
    feature_columns: Sequence[str],
    actual_class: Sequence[str],
    actual_reg: Sequence[float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], bool]:
    try:
        from sklearn.ensemble import ExtraTreesClassifier, ExtraTreesRegressor, RandomForestClassifier, RandomForestRegressor
        from sklearn.linear_model import LogisticRegression, Ridge
        from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except Exception as exc:
        return [], [], [{"task": "sklearn_import", "model": "sklearn", "error": repr(exc)}], False

    x_train = np.array(_matrix(train_rows, feature_columns), dtype=float)
    x_test = np.array(_matrix(test_rows, feature_columns), dtype=float)
    y_class = np.array([str(row["zone_label"]) for row in train_rows])
    y_reg = np.array([float(row["delta_ml"]) for row in train_rows], dtype=float)
    class_candidates = [
        ("logistic_regression", make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, random_state=RANDOM_STATE))),
        ("knn_classifier", KNeighborsClassifier(n_neighbors=max(1, min(3, len(train_rows))))),
        ("random_forest_classifier", RandomForestClassifier(n_estimators=50, random_state=RANDOM_STATE)),
        ("extra_trees_classifier", ExtraTreesClassifier(n_estimators=50, random_state=RANDOM_STATE)),
    ]
    reg_candidates = [
        ("ridge", make_pipeline(StandardScaler(), Ridge())),
        ("knn_regressor", KNeighborsRegressor(n_neighbors=max(1, min(3, len(train_rows))))),
        ("random_forest_regressor", RandomForestRegressor(n_estimators=50, random_state=RANDOM_STATE)),
        ("extra_trees_regressor", ExtraTreesRegressor(n_estimators=50, random_state=RANDOM_STATE)),
    ]
    class_results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for name, model in class_candidates:
        try:
            model.fit(x_train, y_class)
            pred = [str(value) for value in model.predict(x_test)]
        except Exception as exc:
            failures.append({"task": "classification", "model": name, "error": repr(exc)})
            continue
        result = _classification_result(
            name,
            pred,
            actual_class,
            {
                "model_family": name,
                "hyperparameters": _json_safe(model.get_params(deep=False)),
                "scaler": "standard_if_pipeline",
                "imputer": "zero_fill",
            },
        )
        class_results.append(result)
    reg_results: list[dict[str, Any]] = []
    for name, model in reg_candidates:
        try:
            model.fit(x_train, y_reg)
            pred = [float(value) for value in model.predict(x_test)]
        except Exception as exc:
            failures.append({"task": "regression", "model": name, "error": repr(exc)})
            continue
        result = _regression_result(
            name,
            pred,
            actual_reg,
            {
                "model_family": name,
                "hyperparameters": _json_safe(model.get_params(deep=False)),
                "scaler": "standard_if_pipeline",
                "imputer": "zero_fill",
            },
        )
        reg_results.append(result)
    return class_results, reg_results, failures, True


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _classification_result(name: str, pred: Sequence[str], actual: Sequence[str], metadata: Mapping[str, Any]) -> dict[str, Any]:
    correct = sum(1 for a, b in zip(actual, pred) if a == b)
    accuracy = correct / len(actual) if actual else 0.0
    return {"model": name, "predictions": list(pred), "accuracy": round(float(accuracy), 6), "metadata": dict(metadata)}


def _regression_result(name: str, pred: Sequence[float], actual: Sequence[float], metadata: Mapping[str, Any]) -> dict[str, Any]:
    errors = [float(p) - float(a) for p, a in zip(pred, actual)]
    mae = sum(abs(e) for e in errors) / len(errors) if errors else 0.0
    rmse = math.sqrt(sum(e * e for e in errors) / len(errors)) if errors else 0.0
    return {
        "model": name,
        "predictions": [round(float(value), 6) for value in pred],
        "mae": round(float(mae), 6),
        "rmse": round(float(rmse), 6),
        "metadata": dict(metadata),
    }


def evaluate_folder(
    folder: str | Path,
    *,
    output_dir: str | Path = "data/ml",
    fps: float = 25.0,
    window_ml: float = 0.5,
    quick: bool = False,
) -> dict[str, Any]:
    runs = load_runs(folder)
    resampled_runs = [resample_run(run, fps=fps, window_ml=window_ml) for run in runs]
    folds = build_typewise_folds(resampled_runs)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "predictions").mkdir(exist_ok=True)
    (output / "selected_models").mkdir(exist_ok=True)
    (output / "resampled").mkdir(exist_ok=True)

    summary: dict[str, Any] = {
        "schema_version": "typewise_ml_eval_v1",
        "random_state": RANDOM_STATE,
        "fps": float(fps),
        "window_ml": float(window_ml),
        "observation_unit": OBSERVATION_UNIT,
        "versions": _sklearn_versions(),
        "types": {},
        "warnings": [],
    }
    if summary["versions"]["sklearn_version"] is None:
        summary["warnings"].append("scikit-learn unavailable; baseline models only. Install requirements.txt for full model comparison.")

    for run in resampled_runs:
        _write_csv(output / "resampled" / f"{run.path.stem}-25fps.csv", run.rows)

    leaderboard_rows: list[dict[str, Any]] = []
    for fold in folds:
        type_payload = summary["types"].setdefault(
            fold.titration_type, {"folds": [], "macro": {}, "feature_set_macro": {}, "selected_models": {}}
        )
        train_rows = _rows_for_runs(fold.train_runs)
        test_rows = _rows_for_runs(fold.test_runs)
        all_columns = set().union(*(row.keys() for row in train_rows + test_rows))
        actual_zone = [str(row["zone_label"]) for row in test_rows]
        actual_delta = [float(row["delta_ml"]) for row in test_rows]
        fold_id = f"holdout-{fold.held_out_concentration_m:g}M"
        original_row_count = sum(
            len(run.rows)
            for run in runs
            if run.titration_type == fold.titration_type
            and round(run.concentration_m, 8) == round(fold.held_out_concentration_m, 8)
        )

        for feature_set in FEATURE_SETS:
            feature_columns = select_feature_columns(all_columns, feature_set=feature_set)
            if not feature_columns:
                summary["warnings"].append(f"{fold.titration_type}/{fold_id}/{feature_set}: no usable feature columns")
                continue
            assert_no_forbidden_features(feature_columns)
            class_result, reg_result, class_candidates, reg_candidates, candidate_failures = _candidate_predictions(
                train_rows, test_rows, feature_columns, quick=quick
            )
            for failure in candidate_failures:
                summary["warnings"].append(
                    f"{fold.titration_type}/{fold_id}/{feature_set}: {failure['task']} {failure['model']} failed: {failure['error']}"
                )

            prediction_rows = []
            for row, pred_zone, pred_delta in zip(test_rows, class_result["predictions"], reg_result["predictions"]):
                prediction_rows.append(
                    {
                        "titration_type": fold.titration_type,
                        "feature_set": feature_set,
                        "held_out_concentration_m": fold.held_out_concentration_m,
                        "time_s": row.get("time_s", ""),
                        "injected_volume_ml": row.get("injected_volume_ml", ""),
                        "actual_zone": row.get("zone_label", ""),
                        "predicted_zone": pred_zone,
                        "actual_delta_ml": row.get("delta_ml", ""),
                        "predicted_delta_ml": pred_delta,
                        "observation_unit": OBSERVATION_UNIT,
                    }
                )
            pred_path = output / "predictions" / fold.titration_type / feature_set / f"{fold_id}.csv"
            _write_csv(pred_path, prediction_rows)

            fold_payload = {
                "fold_id": fold_id,
                "feature_set": feature_set,
                "titration_type": fold.titration_type,
                "held_out_concentration_m": fold.held_out_concentration_m,
                "original_row_count": original_row_count,
                "resampled_row_count": len(test_rows),
                "observation_unit": OBSERVATION_UNIT,
                "feature_columns": feature_columns,
                "feature_count": len(feature_columns),
                "train_run_paths": [str(run.path) for run in fold.train_runs],
                "test_run_paths": [str(run.path) for run in fold.test_runs],
                "classifier": {"model": class_result["model"], "accuracy": class_result["accuracy"]},
                "regressor": {"model": reg_result["model"], "mae": reg_result["mae"], "rmse": reg_result["rmse"]},
                "classifier_candidates": [
                    {"model": candidate["model"], "accuracy": candidate["accuracy"]} for candidate in class_candidates
                ],
                "regressor_candidates": [
                    {"model": candidate["model"], "mae": candidate["mae"], "rmse": candidate["rmse"]}
                    for candidate in reg_candidates
                ],
                "candidate_failures": candidate_failures,
                "class_counts": dict(Counter(actual_zone)),
                "delta_range_ml": [round(min(actual_delta), 6), round(max(actual_delta), 6)] if actual_delta else [0.0, 0.0],
                "prediction_csv": str(pred_path),
            }
            type_payload["folds"].append(fold_payload)
            leaderboard_rows.append(
                {
                    "titration_type": fold.titration_type,
                    "fold_id": fold_id,
                    "held_out_concentration_m": fold.held_out_concentration_m,
                    "feature_set": feature_set,
                    "classifier": class_result["model"],
                    "classifier_accuracy": class_result["accuracy"],
                    "regressor": reg_result["model"],
                    "regressor_mae": reg_result["mae"],
                    "regressor_rmse": reg_result["rmse"],
                    "observation_unit": OBSERVATION_UNIT,
                }
            )
            _write_selected_model_metadata(
                output / "selected_models" / fold.titration_type / "folds" / feature_set / f"{fold_id}.json",
                fold=fold,
                feature_set=feature_set,
                feature_columns=feature_columns,
                classifier=class_result,
                regressor=reg_result,
                classifier_candidates=class_candidates,
                regressor_candidates=reg_candidates,
                candidate_failures=candidate_failures,
                summary=summary,
            )

    for titration_type, payload in summary["types"].items():
        folds_payload = payload["folds"]
        payload["feature_set_macro"] = _feature_set_macro(folds_payload)
        payload["macro"] = _selected_macro(payload["feature_set_macro"])
        payload["selected_models"] = _write_type_selected_models(
            output / "selected_models" / titration_type,
            titration_type=titration_type,
            folds_payload=folds_payload,
            versions=summary["versions"],
        )
    summary["overall_macro"] = _overall_macro(summary["types"])

    (output / "typewise_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(output / "typewise_summary.csv", leaderboard_rows)
    (output / "report.md").write_text(_render_report(summary), encoding="utf-8")
    return summary


def _feature_set_macro(folds_payload: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for feature_set in FEATURE_SETS:
        rows = [fold for fold in folds_payload if fold.get("feature_set") == feature_set]
        if not rows:
            continue
        result[feature_set] = {
            "classifier_accuracy": round(float(statistics.mean(f["classifier"]["accuracy"] for f in rows)), 6),
            "regressor_mae": round(float(statistics.mean(f["regressor"]["mae"] for f in rows)), 6),
            "regressor_rmse": round(float(statistics.mean(f["regressor"]["rmse"] for f in rows)), 6),
            "fold_count": len(rows),
        }
    return result


def _selected_macro(feature_set_macro: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    if not feature_set_macro:
        return {"classifier_accuracy": 0.0, "regressor_mae": 0.0, "regressor_rmse": 0.0, "fold_count": 0}
    best_classifier_set, best_classifier = max(
        feature_set_macro.items(), key=lambda item: item[1]["classifier_accuracy"]
    )
    best_regressor_set, best_regressor = min(feature_set_macro.items(), key=lambda item: item[1]["regressor_mae"])
    return {
        "classifier_accuracy": best_classifier["classifier_accuracy"],
        "classifier_feature_set": best_classifier_set,
        "regressor_mae": best_regressor["regressor_mae"],
        "regressor_rmse": best_regressor["regressor_rmse"],
        "regressor_feature_set": best_regressor_set,
        "fold_count": max(int(item.get("fold_count", 0)) for item in feature_set_macro.values()),
    }


def _write_type_selected_models(
    output_dir: Path,
    *,
    titration_type: str,
    folds_payload: Sequence[Mapping[str, Any]],
    versions: Mapping[str, Any],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    classifier_entries = []
    regressor_entries = []
    for feature_set in FEATURE_SETS:
        rows = [fold for fold in folds_payload if fold.get("feature_set") == feature_set]
        if not rows:
            continue
        classifier_by_model: dict[str, list[float]] = defaultdict(list)
        regressor_by_model: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for fold in rows:
            for candidate in fold.get("classifier_candidates", []):
                classifier_by_model[str(candidate["model"])].append(float(candidate["accuracy"]))
            for candidate in fold.get("regressor_candidates", []):
                regressor_by_model[str(candidate["model"])].append((float(candidate["mae"]), float(candidate["rmse"])))
        for model, values in classifier_by_model.items():
            classifier_entries.append(
                {
                    "feature_set": feature_set,
                    "model": model,
                    "mean_accuracy": round(float(statistics.mean(values)), 6),
                    "fold_count": len(values),
                }
            )
        for model, values in regressor_by_model.items():
            regressor_entries.append(
                {
                    "feature_set": feature_set,
                    "model": model,
                    "mean_mae": round(float(statistics.mean(value[0] for value in values)), 6),
                    "mean_rmse": round(float(statistics.mean(value[1] for value in values)), 6),
                    "fold_count": len(values),
                }
            )
    selected_classifier = max(classifier_entries, key=lambda item: item["mean_accuracy"])
    selected_regressor = min(regressor_entries, key=lambda item: item["mean_mae"])
    feature_columns_by_set: dict[str, list[str]] = {}
    for feature_set in FEATURE_SETS:
        for fold in folds_payload:
            if fold.get("feature_set") == feature_set:
                feature_columns_by_set[feature_set] = list(fold.get("feature_columns", []))
                break
    fold_run_identifiers = [
        {
            "fold_id": fold["fold_id"],
            "feature_set": fold["feature_set"],
            "held_out_concentration_m": fold["held_out_concentration_m"],
            "train_run_paths": fold["train_run_paths"],
            "test_run_paths": fold["test_run_paths"],
        }
        for fold in folds_payload
    ]
    classifier_payload = _type_selected_payload(
        titration_type=titration_type,
        task="classifier",
        selected=selected_classifier,
        leaderboard=classifier_entries,
        feature_columns=feature_columns_by_set.get(str(selected_classifier["feature_set"]), []),
        fold_run_identifiers=fold_run_identifiers,
        versions=versions,
    )
    regressor_payload = _type_selected_payload(
        titration_type=titration_type,
        task="regressor",
        selected=selected_regressor,
        leaderboard=regressor_entries,
        feature_columns=feature_columns_by_set.get(str(selected_regressor["feature_set"]), []),
        fold_run_identifiers=fold_run_identifiers,
        versions=versions,
    )
    (output_dir / "classifier.json").write_text(json.dumps(classifier_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "regressor.json").write_text(json.dumps(regressor_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"classifier": selected_classifier, "regressor": selected_regressor}


def _type_selected_payload(
    *,
    titration_type: str,
    task: str,
    selected: Mapping[str, Any],
    leaderboard: Sequence[Mapping[str, Any]],
    feature_columns: Sequence[str],
    fold_run_identifiers: Sequence[Mapping[str, Any]],
    versions: Mapping[str, Any],
) -> dict[str, Any]:
    assert_no_forbidden_features(feature_columns)
    return {
        "schema_version": "typewise_selected_model_metadata_v1",
        "selection_level": "per_type",
        "task": task,
        "random_state": RANDOM_STATE,
        "titration_type": titration_type,
        "feature_set": selected["feature_set"],
        "model": selected["model"],
        "selected_metrics": dict(selected),
        "feature_columns": list(feature_columns),
        "forbidden_feature_audit": {"status": "passed", "forbidden_features": []},
        "candidate_leaderboard": list(leaderboard),
        "fold_run_identifiers": list(fold_run_identifiers),
        "versions": dict(versions),
        "selection_rationale": "Per-type selected model is chosen from leave-one-concentration-out fold averages and reported as proof-of-concept, not universal accuracy.",
    }


def _overall_macro(types: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    if not types:
        return {}
    return {
        "classifier_accuracy": round(float(statistics.mean(t["macro"]["classifier_accuracy"] for t in types.values())), 6),
        "regressor_mae": round(float(statistics.mean(t["macro"]["regressor_mae"] for t in types.values())), 6),
        "regressor_rmse": round(float(statistics.mean(t["macro"]["regressor_rmse"] for t in types.values())), 6),
        "type_count": len(types),
    }


def _write_selected_model_metadata(
    path: Path,
    *,
    fold: TypewiseFold,
    feature_set: str,
    feature_columns: Sequence[str],
    classifier: Mapping[str, Any],
    regressor: Mapping[str, Any],
    classifier_candidates: Sequence[Mapping[str, Any]],
    regressor_candidates: Sequence[Mapping[str, Any]],
    candidate_failures: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> None:
    assert_no_forbidden_features(feature_columns)
    payload = {
        "schema_version": "typewise_selected_model_metadata_v1",
        "selection_level": "fold",
        "random_state": RANDOM_STATE,
        "titration_type": fold.titration_type,
        "feature_set": feature_set,
        "held_out_concentration_m": fold.held_out_concentration_m,
        "train_run_paths": [str(run.path) for run in fold.train_runs],
        "test_run_paths": [str(run.path) for run in fold.test_runs],
        "feature_columns": list(feature_columns),
        "forbidden_feature_audit": {"status": "passed", "forbidden_features": []},
        "classifier": {"model": classifier["model"], "metrics": {"accuracy": classifier["accuracy"]}, "metadata": classifier["metadata"]},
        "regressor": {"model": regressor["model"], "metrics": {"mae": regressor["mae"], "rmse": regressor["rmse"]}, "metadata": regressor["metadata"]},
        "candidate_leaderboard": {
            "classifiers": [{"model": item["model"], "accuracy": item["accuracy"]} for item in classifier_candidates],
            "regressors": [{"model": item["model"], "mae": item["mae"], "rmse": item["rmse"]} for item in regressor_candidates],
        },
        "candidate_failures": list(candidate_failures),
        "versions": summary["versions"],
        "selection_rationale": "Fold-level selected model is compared against baseline and must be reported as proof-of-concept because only three concentrations per type exist.",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _render_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# 타입별 머신러닝 당량점 분석 보고서",
        "",
        "이 분석은 통합 모델 하나로 모든 적정 종류를 섞지 않고, 적정 종류별 모델을 따로 비교한다.",
        "이론 당량점은 정답 라벨과 평가 기준으로만 사용하고, 모델 입력 feature에는 넣지 않았다.",
        "25fps 보간 행은 frame-level observations이며 독립 실험 수가 늘어난 것으로 해석하지 않는다.",
        "따라서 결과는 proof-of-concept이며, 더 많은 반복 실험 전에는 일반화 정확도라고 주장하지 않는다.",
        "",
        "## fold-first 검증 근거",
        "",
    ]
    for titration_type, payload in sorted(summary.get("types", {}).items()):
        lines.append(f"### `{titration_type}`")
        for fold in sorted(payload.get("folds", []), key=lambda item: (item["held_out_concentration_m"], item["feature_set"])):
            lines.append(
                f"- held-out {fold['held_out_concentration_m']} M / {fold['feature_set']}: "
                f"원본 {fold['original_row_count']}행 → 25fps {fold['resampled_row_count']}행, "
                f"classifier={fold['classifier']['model']} acc={fold['classifier']['accuracy']}, "
                f"regressor={fold['regressor']['model']} MAE={fold['regressor']['mae']} mL"
            )
        lines.append("")
    lines.extend(
        [
        "## 타입별 요약",
        "",
        ]
    )
    for titration_type, payload in sorted(summary.get("types", {}).items()):
        macro = payload.get("macro", {})
        lines.append(
            f"- `{titration_type}`: folds={macro.get('fold_count', 0)}, "
            f"best_classifier_set={macro.get('classifier_feature_set', '')}, "
            f"classifier_accuracy={macro.get('classifier_accuracy', 0)}, "
            f"best_regressor_set={macro.get('regressor_feature_set', '')}, "
            f"regressor_mae_ml={macro.get('regressor_mae', 0)}"
        )
        for feature_set, feature_macro in sorted(payload.get("feature_set_macro", {}).items()):
            lines.append(
                f"  - {feature_set}: acc={feature_macro.get('classifier_accuracy', 0)}, "
                f"MAE={feature_macro.get('regressor_mae', 0)} mL"
            )
    if summary.get("warnings"):
        lines.extend(["", "## 주의", ""])
        lines.extend(f"- {warning}" for warning in summary["warnings"])
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate typewise ML models around titration equivalence zones.")
    parser.add_argument("folder", help="Folder containing run CSV files")
    parser.add_argument("--output-dir", default="data/ml", help="Output artifact directory")
    parser.add_argument("--fps", type=float, default=25.0, help="Resampling frame rate")
    parser.add_argument("--window-ml", type=float, default=0.5, help="Equivalence-zone half-window in mL")
    parser.add_argument("--quick", action="store_true", help="Use baseline-only quick evaluation")
    args = parser.parse_args(argv)
    summary = evaluate_folder(args.folder, output_dir=args.output_dir, fps=args.fps, window_ml=args.window_ml, quick=args.quick)
    print(json.dumps({"types": sorted(summary["types"].keys()), "output_dir": args.output_dir}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
