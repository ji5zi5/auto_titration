#!/usr/bin/env python3
"""Refresh the existing Web-GPT handoff bundle with current report visuals."""
from __future__ import annotations

import csv
import hashlib
import re
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PACKAGE_NAME = "웹GPT_보고서_최종보강자료_2026-08-06"
PACKAGE = DIST / PACKAGE_NAME
ZIP_PATH = DIST / f"{PACKAGE_NAME}.zip"
REPORT = ROOT / "docs/science_fair_report_national_formatted.md"
CORE_FIGURES = ROOT / "docs/report_evidence_no_new_wet/figures"
COMPARISON_FIGURES = ROOT / "docs/report_evidence_no_new_wet/comparison_visuals"
REPORT_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(source)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def copy_report_images(report_destination: Path) -> None:
    """Mirror every Markdown image beside the packaged report so links resolve."""
    text = REPORT.read_text(encoding="utf-8")
    for relative_text in REPORT_IMAGE_PATTERN.findall(text):
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Unsafe report image path: {relative_text}")
        copy(ROOT / "docs" / relative, report_destination.parent / relative)


def copy_visual_reproduction_inputs() -> None:
    """Copy the exact source paths expected by make_comparison_visuals.py."""
    copy(
        ROOT / "tools/make_comparison_visuals.py",
        PACKAGE / "tools/make_comparison_visuals.py",
    )
    files = (
        "data/ml/type_conditioned_sensor_sequence_search/summary.json",
        "data/ml/type_conditioned_sensor_sequence_search/outer_predictions.csv",
        "docs/report_evidence_no_new_wet/figures/source_data/01_02_condition_predictions.csv",
        "data/report/manual_titration_results.csv",
        "data/analysis/non_ml_baseline_comparison/per_run_predictions.csv",
        "data/analysis/non_ml_baseline_comparison/overall_comparison.csv",
        "data/ml/report_modality_sensor_features_only/overall_comparison.csv",
        "data/ml/report_modality_sensor_features_only/typewise_selection_color_thermal_fusion.csv",
        "data/analysis/july_unknown_repeatability/july_unknown_repeatability_summary.json",
        "data/ml/curve_equivalence_current/model_algorithm_comparison.csv",
    )
    for relative_text in files:
        copy(ROOT / relative_text, PACKAGE / relative_text)
    copy_tree(ROOT / "머신러닝용 파일모음", PACKAGE / "머신러닝용 파일모음")


def update_instructions() -> None:
    path = PACKAGE / "00_안내/00_웹GPT_작업지시서.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "`06_최신그래프`의 PNG 5개는 모두 현재 결과에서 300 dpi로 다시 생성한 최종본이다.",
        "`06_최신그래프/01_핵심결과`와 `06_최신그래프/02_비교시각자료`의 PNG는 현재 근거자료에서 300 dpi로 다시 생성한 최종본이다.",
    )
    marker = "## 비교 시각자료 우선순위"
    if marker not in text:
        text += f"""

{marker}

1. `02_비교시각자료/03_advanced_family_selection_map.png` — 탐색한 여덟 알고리즘 계열과 종류별 선택 결과
2. `02_비교시각자료/02_selected_evaluator_by_type.png` — PLS·RBF KRR·LDA·QDA의 종류별 선택과 MAPE
3. `02_비교시각자료/06_comprehensive_method_mape.png` — 수동·비머신러닝·센서 입력군 ML·최종 조건부 모델 비교
4. `02_비교시각자료/07_comprehensive_method_mae_rmse.png` — 같은 방식의 MAE·RMSE 비교
5. `02_비교시각자료/04_condition_method_ape_heatmap.png` — 12조건별 판정 방식 오차
6. `02_비교시각자료/09_manual_vs_final_condition_ape.png` — 수동 기록과 최종 모델의 조건별 참고 비교
7. `02_비교시각자료/12_unknown_repeatability_concentration.png` — 동일 미지 시료 3회 반복성

초기 Ridge·KNN·Random Forest·Extra Trees 비교와 최종 0.30% 모델은 특징 표현과 탐색 절차가 다르므로 같은 파이프라인의 순위처럼 합치지 않는다. 비교 그림의 정확한 범위와 캡션은 `02_비교시각자료/README.md`를 따른다.
"""
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def refresh_files() -> None:
    if not PACKAGE.is_dir():
        raise FileNotFoundError(PACKAGE)
    report_destination = PACKAGE / "01_현재보고서/과학전람회_보고서_현재본문.md"
    copy(REPORT, report_destination)
    copy_report_images(report_destination)
    for name in (
        "제72회_작품설명서_자동생성검토본.hwpx",
        "제72회_작품설명서_개인정보삭제_자동생성검토본.hwpx",
    ):
        copy(ROOT / "docs" / name, PACKAGE / "01_현재보고서" / name)

    latest = PACKAGE / "06_최신그래프"
    if latest.exists():
        shutil.rmtree(latest)
    core_out = latest / "01_핵심결과"
    core_out.mkdir(parents=True)
    for path in sorted(CORE_FIGURES.glob("*.png")):
        copy(path, core_out / path.name)
    copy_tree(CORE_FIGURES / "source_data", core_out / "source_data")
    copy_tree(COMPARISON_FIGURES, latest / "02_비교시각자료")
    copy(
        ROOT / "docs/report_evidence_no_new_wet/visual_audit.json",
        latest / "시각자료_검증결과.json",
    )
    copy_visual_reproduction_inputs()
    update_instructions()


def rebuild_manifests() -> None:
    manifest_paths = {PACKAGE / "SHA256SUMS", PACKAGE / "파일목록.csv"}
    files = [
        path
        for path in sorted(PACKAGE.rglob("*"))
        if path.is_file() and path not in manifest_paths
    ]
    with (PACKAGE / "파일목록.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=("경로", "크기_byte", "SHA256")
        )
        writer.writeheader()
        for path in files:
            writer.writerow(
                {
                    "경로": path.relative_to(PACKAGE).as_posix(),
                    "크기_byte": path.stat().st_size,
                    "SHA256": sha256(path),
                }
            )
    sums = [
        f"{sha256(path)}  {path.relative_to(PACKAGE).as_posix()}" for path in files
    ]
    (PACKAGE / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")


def rebuild_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(
        ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in sorted(PACKAGE.rglob("*")):
            if path.is_file():
                archive.write(path, f"{PACKAGE_NAME}/{path.relative_to(PACKAGE)}")


def main() -> None:
    refresh_files()
    rebuild_manifests()
    rebuild_zip()
    print(f"package: {PACKAGE}")
    print(f"zip: {ZIP_PATH}")
    print(f"files: {sum(1 for path in PACKAGE.rglob('*') if path.is_file())}")
    print(f"zip_sha256: {sha256(ZIP_PATH)}")


if __name__ == "__main__":
    main()
