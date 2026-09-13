#!/usr/bin/env python3
"""Validate the teacher-feedback science-fair report revision.

The validator checks the OOXML package, narrative contract, result ordering,
table/figure numbering, measured values, and the scope boundaries that must
not be overstated.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from lxml import etree
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DOCX = ROOT / "전국과학전람회_자격루_비접촉스마트자동적정장치_교사피드백반영본.docx"
RESULT = ROOT / ".omx/specs/autoresearch-report-revision/result.json"
FIGURE_DIR = ROOT / "docs/report_revision_figures"

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}
IMAGE_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
)


def text(element: etree._Element) -> str:
    return "".join(element.xpath(".//w:t/text()", namespaces=NS))


def main() -> None:
    checks: dict[str, bool] = {}
    errors: list[str] = []

    checks["output_exists"] = DOCX.exists() and DOCX.stat().st_size > 1_000_000
    if not checks["output_exists"]:
        errors.append("output DOCX is missing or unexpectedly small")
        write_result(checks, errors)
        raise SystemExit(1)

    with zipfile.ZipFile(DOCX) as archive:
        checks["zip_integrity"] = archive.testzip() is None
        names = set(archive.namelist())
        document = etree.fromstring(archive.read("word/document.xml"))
        rels = etree.fromstring(archive.read("word/_rels/document.xml.rels"))

        missing_images = []
        for relationship in rels:
            if relationship.get("Type") != IMAGE_REL_TYPE:
                continue
            target = relationship.get("Target", "")
            package_name = f"word/{target}"
            if package_name not in names:
                missing_images.append(package_name)
        checks["image_relationships_resolve"] = not missing_images
        if missing_images:
            errors.append(f"missing related images: {missing_images}")

    body = document.xpath("./w:body", namespaces=NS)[0]
    body_text = "\n".join(
        text(child).strip()
        for child in body
        if text(child).strip()
    )

    exact_title = "자격루에서 착안한 비접촉 스마트 자동 적정 장치"
    checks["exact_title"] = body_text.count(exact_title) == 1
    checks["jagyeongnu_principle"] = all(
        phrase in body_text
        for phrase in [
            "일정한 흐름을 이용해 누적량을 계산",
            "흐름·시간·누적량을 연결하는 계량 원리",
        ]
    )

    ordered_headings = [
        "3. 비접촉 스마트 적정 장치를 이용한 당량점 부피 추정 결과",
        "4. 동일 조건 반복 측정과 미지 농도 계산",
        "5. 수동 적정 결과",
        "6. 비머신러닝과 머신러닝의 성능 비교",
        "7. 센서 입력 구성과 적정 종류별 결과",
        "8. 수동 적정과 비접촉 스마트 적정 장치의 비교",
    ]
    positions = [body_text.find(heading) for heading in ordered_headings]
    checks["result_order"] = all(position >= 0 for position in positions) and (
        positions == sorted(positions)
    )

    checks["no_added_duplicate_sections"] = all(
        forbidden not in body_text
        for forbidden in [
            "15. 수동 적정과 스마트 적정의 역할 비교",
            "16. 머신러닝 결과의 실험적 의미",
        ]
    ) and "15. 장치 운용 절차와 안전성" in body_text

    table_numbers = [
        int(value)
        for value in re.findall(r"표\s+(\d+)\.", body_text)
    ]
    figure_numbers = [
        int(value)
        for value in re.findall(r"그림\s+(\d+)\.", body_text)
    ]
    checks["table_numbering"] = table_numbers == list(range(1, 8))
    checks["figure_numbering"] = figure_numbers == list(range(1, 32))

    required_values = [
        "장치 기반 센서 융합 모델 추정값 (mL)",
        "0.476",
        "0.831",
        "1.52",
        "수동 적정",
        "0.367",
        "0.406",
        "1.22",
        "4.67",
        "5.65",
        "67.4%",
        "3.85%",
    ]
    checks["measured_values_preserved"] = all(
        value in body_text for value in required_values
    )

    checks["model_input_scope"] = all(
        phrase in body_text
        for phrase in [
            "현재 누적 주입량",
            "머신러닝 입력에서 제외",
            "센서·실험조건 특징만 남겼다",
        ]
    )
    checks["android_scope"] = (
        "12회 습식 실험과 머신러닝 성능 평가는 Windows 수집 경로의 자료만 사용"
        in body_text
    )
    checks["csv_scope"] = all(
        phrase in body_text
        for phrase in [
            "0.04초 간격의 시험 입력",
            "CSV 저장 경로의 성능 시험",
        ]
    )
    checks["auto_stop_scope"] = all(
        phrase in body_text
        for phrase in [
            "실제 12회 산·염기 적정은 사람이 정지한 자료",
            "소프트웨어 동작을 확인한 결과",
        ]
    )

    forbidden_phrases = [
        "자동 적정의 추정 당량점 부피",
        "스마트 자동 적정 보조장치",
        "25 fps 입력",
        "수동 적정보다 항상 더 정확",
    ]
    checks["forbidden_phrases_absent"] = all(
        phrase not in body_text for phrase in forbidden_phrases
    )

    required_figures = [
        "01_smart_theory_vs_prediction.png",
        "02_smart_error_by_condition.png",
        "03_manual_vs_smart_by_condition.png",
        "04_method_comparison_mape.png",
        "06_sensor_modality_comparison.png",
        "08_repeatability_three_runs.png",
        "09_csv_recording_throughput.png",
    ]
    figure_checks = []
    for filename in required_figures:
        path = FIGURE_DIR / filename
        valid = path.exists()
        if valid:
            with Image.open(path) as image:
                valid = image.width >= 1_000 and image.height >= 700
        figure_checks.append(valid)
    checks["core_figures_valid"] = all(figure_checks)

    for name, passed in checks.items():
        if not passed and not any(name in error for error in errors):
            errors.append(f"failed check: {name}")

    write_result(checks, errors)
    if errors:
        print(json.dumps({"passed": False, "errors": errors}, ensure_ascii=False))
        raise SystemExit(1)
    print(
        json.dumps(
            {
                "passed": True,
                "output_artifact_path": str(DOCX.relative_to(ROOT)),
                "checks": checks,
            },
            ensure_ascii=False,
        )
    )


def write_result(checks: dict[str, bool], errors: list[str]) -> None:
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    passed = not errors and all(checks.values())
    payload = {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "summary": (
            "Teacher-feedback report revision passed OOXML, narrative, data, "
            "scope, numbering, and figure validation."
            if passed
            else "Teacher-feedback report revision validation failed."
        ),
        "output_artifact_path": str(DOCX.relative_to(ROOT)),
        "checks": checks,
        "errors": errors,
    }
    RESULT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
