#!/usr/bin/env python3
"""Validate poster visual pack structure, provenance, and print-readiness."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Sequence

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_IDS = {
    "chart_method_mape", "chart_modality", "chart_typewise", "chart_actual_predicted",
    "chart_condition_ape", "chart_sensor_curves", "chart_experiment_matrix", "chart_performance",
    "diagram_system", "diagram_research_flow", "diagram_jagyeokru", "diagram_auto_stop",
    "diagram_recording", "photo_apparatus", "photo_hardware", "photo_experiment", "photo_software",
}
FORBIDDEN_SOURCE_TOKENS = (
    "type_conditioned_modality_ranker_search",
    "optimized_modality",
    "posthoc_typewise_model_selection",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def resolve_source_uri(uri: str, output: Path) -> Path:
    if uri.startswith("repo://"):
        return ROOT / uri[len("repo://"):]
    if uri.startswith("pack://"):
        return output / uri[len("pack://"):]
    if uri.startswith("file://"):
        return Path(uri[len("file://"):])
    raise ValueError(f"unsupported source URI: {uri}")


def validate(manifest_path: Path) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output = manifest_path.parent
    ids = {entry["id"] for entry in manifest.get("assets", [])}
    missing_ids = sorted(REQUIRED_IDS - ids)
    if missing_ids:
        failures.append(f"missing required asset ids: {missing_ids}")
    if manifest.get("style", {}).get("embedded_titles") is not False:
        failures.append("pack style must disable embedded titles")
    palette = manifest.get("palette", {})
    expected_palette = {"color": "#2563EB", "thermal": "#F59E0B", "fusion": "#10B981"}
    for key, value in expected_palette.items():
        if palette.get(key) != value:
            failures.append(f"palette mismatch for {key}: {palette.get(key)}")
    scope_text = json.dumps(manifest.get("scientific_scope", {}), ensure_ascii=False)
    if "1.55%" not in scope_text or "3.66%" not in scope_text or "1.52%" not in scope_text:
        failures.append("scientific scope does not declare poster modality values")

    dimensions = {}
    referenced_files = set()
    media_hashes: dict[str, list[str]] = {}
    for entry in manifest.get("assets", []):
        path = output / entry["file"]
        referenced_files.add(Path(entry["file"]))
        if not path.is_file():
            failures.append(f"missing asset file: {entry['file']}")
            continue
        if entry.get("poster_eligible") is not True:
            failures.append(f"required asset not poster eligible: {entry['id']}")
        if entry.get("embedded_title") is not False:
            failures.append(f"embedded title not disabled: {entry['id']}")
        if not entry.get("source_paths"):
            failures.append(f"missing provenance: {entry['id']}")
        else:
            for uri in entry["source_paths"]:
                try:
                    source_path = resolve_source_uri(uri, output)
                except ValueError as error:
                    failures.append(str(error))
                    continue
                if not source_path.is_file() and not source_path.is_dir():
                    failures.append(f"unresolved provenance for {entry['id']}: {uri}")
        source_text = " ".join(entry.get("source_paths", [])).lower()
        for token in FORBIDDEN_SOURCE_TOKENS:
            if token in source_text:
                failures.append(f"forbidden post-hoc source in {entry['id']}: {token}")
        if path.suffix.lower() == ".png":
            with Image.open(path) as image:
                dimensions[entry["id"]] = [image.width, image.height]
                if image.width < 1800:
                    failures.append(f"image width below 1800 px: {entry['file']} ({image.width})")
                if image.height < 900:
                    failures.append(f"image height below 900 px: {entry['file']} ({image.height})")
                dpi = image.info.get("dpi")
                if not dpi or min(float(dpi[0]), float(dpi[1])) < 295:
                    failures.append(f"image DPI below print target: {entry['file']} ({dpi})")
        media_hashes.setdefault(sha256(path), []).append(entry["file"])
        svg = entry.get("svg")
        if entry["kind"] in {"chart", "diagram"} and svg and not (output / svg).is_file():
            failures.append(f"missing SVG companion: {svg}")
        if svg:
            referenced_files.add(Path(svg))

    generated_media = {
        path.relative_to(output)
        for directory in (output / "01_핵심그래프", output / "02_구성도와흐름도", output / "03_실제사진")
        if directory.is_dir()
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in {".png", ".svg"}
    }
    unreferenced = sorted(str(path) for path in generated_media - referenced_files)
    if unreferenced:
        failures.append(f"unreferenced/obsolete media remains: {unreferenced}")
    duplicate_media = [paths for paths in media_hashes.values() if len(paths) > 1]
    if duplicate_media:
        failures.append(f"duplicate poster media detected: {duplicate_media}")

    builder_source = (ROOT / "tools/build_poster_visual_pack.py").read_text(encoding="utf-8")
    if ".set_title(" in builder_source or ".suptitle(" in builder_source:
        failures.append("builder contains embedded chart-title calls")
    modality_svg = output / "01_핵심그래프/02_센서입력군_비교.svg"
    if modality_svg.is_file():
        svg_text = modality_svg.read_text(encoding="utf-8").lower()
        for color in ("#2563eb", "#f59e0b", "#10b981"):
            if color not in svg_text:
                failures.append(f"modality SVG missing palette color {color}")

    method_path = output / "04_원본수치/method_comparison.csv"
    if method_path.is_file():
        methods = {row["method"]: row for row in read_csv(method_path)}
        expected = {
            "수동 적정": 2.0,
            "색 최대 기울기": 4.673611,
            "색·온도 임계값": 5.65,
            "ML 색상": 1.552056,
            "ML 열화상": 3.661547,
            "ML 색상+열화상": 1.524496,
        }
        for method, expected_value in expected.items():
            observed = float(methods[method]["mape_percent"])
            if abs(observed - expected_value) > 1e-6:
                failures.append(f"modality source mismatch {method}: {observed}")
    else:
        failures.append("missing method comparison source")

    prediction_path = output / "04_원본수치/fusion_predictions.csv"
    if prediction_path.is_file():
        predictions = read_csv(prediction_path)
        if len(predictions) != 12:
            failures.append(f"fusion prediction row count != 12: {len(predictions)}")
        mape = sum(float(row["absolute_percentage_error"]) for row in predictions) / max(1, len(predictions))
        if abs(mape - 1.524496388888889) > 1e-6:
            failures.append(f"fusion MAPE mismatch: {mape}")
    else:
        failures.append("missing fusion predictions source")

    typewise_path = output / "04_원본수치/fusion_typewise.csv"
    if typewise_path.is_file():
        observed = {
            row["titration_type"]: float(row["mape_percent_on_available_type_runs"])
            for row in read_csv(typewise_path)
        }
        expected_typewise = {
            "strong_acid_strong_base": 0.248597,
            "strong_acid_weak_base": 0.968558,
            "weak_acid_strong_base": 3.214696,
            "weak_acid_weak_base": 1.666134,
        }
        for key, value in expected_typewise.items():
            if abs(observed.get(key, -1) - value) > 1e-6:
                failures.append(f"typewise MAPE mismatch {key}: {observed.get(key)}")
    else:
        failures.append("missing fusion typewise source")

    experiment_summary = output / "04_원본수치/experiment_summary.csv"
    if experiment_summary.is_file():
        row = read_csv(experiment_summary)[0]
        if int(row["run_count"]) != 12 or int(row["recorded_timeseries_row_count"]) != 1822:
            failures.append("experiment summary does not prove 12 runs / 1822 rows")
    else:
        failures.append("missing experiment summary source")

    curve_reference = output / "04_원본수치/curve_reference.csv"
    if curve_reference.is_file():
        row = read_csv(curve_reference)[0]
        if abs(float(row["theoretical_equivalence_volume_ml"]) - 30.0) > 1e-9:
            failures.append("curve reference does not prove 30 mL line")
    else:
        failures.append("missing curve reference source")

    system_metrics_path = output / "04_원본수치/system_validation_metrics.csv"
    if system_metrics_path.is_file():
        metrics = {row["metric"]: float(row["value"]) for row in read_csv(system_metrics_path)}
        expected_metrics = {
            "camera_sync_mean_absolute_ms": 3.66,
            "official_dll_rows_per_s": 24.93,
            "official_dll_p95_ms": 8.91,
            "recording_dropped_rows": 0.0,
            "step5_nominal_ml": 0.0495,
        }
        for key, value in expected_metrics.items():
            if abs(metrics.get(key, float("nan")) - value) > 1e-9:
                failures.append(f"system metric mismatch {key}: {metrics.get(key)}")
    else:
        failures.append("missing system validation source")

    source_manifest_path = output / "04_원본수치/source_manifest.csv"
    if source_manifest_path.is_file():
        for row in read_csv(source_manifest_path):
            original = resolve_source_uri(row["original_source"], output)
            copy = resolve_source_uri(row["pack_copy"], output)
            if not original.is_file() or not copy.is_file():
                failures.append(f"source manifest path missing: {row['source_id']}")
                continue
            if sha256(original) != row["sha256"] or sha256(copy) != row["sha256"]:
                failures.append(f"source manifest hash mismatch: {row['source_id']}")
    else:
        failures.append("missing source manifest")

    guide = output / "05_배치가이드/포스터_배치가이드.md"
    if not guide.is_file():
        failures.append("missing insertion guide")
    else:
        guide_text = guide.read_text(encoding="utf-8")
        if "0.295%·0.340%" not in guide_text or "사용하지 않는다" not in guide_text:
            failures.append("guide does not exclude post-hoc values")
        if "Android Mini2 raw" not in guide_text:
            failures.append("guide lacks Android raw warning")
        if "명목 계산값" not in guide_text:
            failures.append("guide lacks STEP 5 nominal warning")

    notes = {entry["id"]: str(entry.get("note") or "") for entry in manifest.get("assets", [])}
    for asset_id in ("chart_modality", "chart_typewise", "chart_actual_predicted", "chart_condition_ape"):
        if "독립 검증" not in notes.get(asset_id, ""):
            failures.append(f"development-only warning missing from {asset_id}")
    for asset_id in ("chart_performance", "diagram_recording"):
        note = notes.get(asset_id, "")
        if "저장 raw" not in note or "습식" not in note:
            failures.append(f"saved-raw/live-USB scope missing from {asset_id}")

    checksums = output / "SHA256SUMS.txt"
    if not checksums.is_file():
        failures.append("missing SHA256SUMS.txt")
    else:
        listed = {}
        for line in checksums.read_text(encoding="utf-8").splitlines():
            digest, relative = line.split("  ", 1)
            listed[relative] = digest
            path = output / relative
            if not path.is_file() or sha256(path) != digest:
                failures.append(f"checksum mismatch: {relative}")
        actual_files = {
            str(path.relative_to(output))
            for path in output.rglob("*")
            if path.is_file() and path.name != "SHA256SUMS.txt"
        }
        if set(listed) != actual_files:
            failures.append(
                f"checksum coverage mismatch missing={sorted(actual_files - set(listed))} "
                f"extra={sorted(set(listed) - actual_files)}"
            )

    zip_path = output.parent / f"{output.name}.zip"
    if not zip_path.is_file():
        failures.append(f"missing delivery zip: {zip_path.name}")
    elif zip_path.stat().st_size < 100_000:
        failures.append("delivery zip is unexpectedly small")
    else:
        with zipfile.ZipFile(zip_path) as archive:
            zip_files = {
                name: archive.read(name)
                for name in archive.namelist()
                if not name.endswith("/")
            }
        expected_zip_names = {
            str(Path(output.name) / path.relative_to(output)): path
            for path in output.rglob("*")
            if path.is_file()
        }
        if set(zip_files) != set(expected_zip_names):
            failures.append("ZIP file inventory does not exactly match pack directory")
        else:
            for name, path in expected_zip_names.items():
                if hashlib.sha256(zip_files[name]).hexdigest() != sha256(path):
                    failures.append(f"ZIP byte mismatch: {name}")

    result = {
        "ok": not failures,
        "manifest": str(manifest_path),
        "asset_count": len(manifest.get("assets", [])),
        "dimensions": dimensions,
        "failures": failures,
        "warnings": warnings,
        "zip": str(zip_path),
    }
    report = output / "validation_report.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result["ok"]:
        files = sorted(
            path for path in output.rglob("*")
            if path.is_file() and path.name != "SHA256SUMS.txt"
        )
        checksums.write_text(
            "".join(f"{sha256(path)}  {path.relative_to(output)}\n" for path in files),
            encoding="utf-8",
        )
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(output.rglob("*")):
                if path.is_file():
                    archive.write(path, Path(output.name) / path.relative_to(output))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    result = validate(Path(args.manifest))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
