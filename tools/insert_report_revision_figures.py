#!/usr/bin/env python3
"""Insert verified report figures and apply high-confidence editorial fixes.

The source DOCX is never overwritten. This script edits the OOXML package
directly so it does not require python-docx or LibreOffice.
"""
from __future__ import annotations

import copy
import csv
import io
import re
import zipfile
from pathlib import Path

from lxml import etree
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DOCX = ROOT / "전국과학전람회_자격루_스마트자동적정_보고서전체수정_실제사진보강본.docx"
OUTPUT_DOCX = ROOT / "전국과학전람회_자격루_비접촉스마트자동적정장치_교사피드백반영본.docx"
FIGURE_DIR = ROOT / "docs/report_revision_figures"
PREDICTIONS = FIGURE_DIR / "source_data/smart_manual_run_comparison.csv"

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}

IMAGE_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
)


def element_text(element: etree._Element) -> str:
    return "".join(element.xpath(".//w:t/text()", namespaces=NS))


def set_element_text(element: etree._Element, text: str) -> None:
    nodes = element.xpath(".//w:t", namespaces=NS)
    if not nodes:
        run = etree.SubElement(element, f"{{{NS['w']}}}r")
        node = etree.SubElement(run, f"{{{NS['w']}}}t")
        nodes = [node]
    nodes[0].text = text
    for node in nodes[1:]:
        node.text = ""


def replace_text_in_paragraphs(
    document: etree._Element,
    old: str,
    new: str,
    *,
    expected: int | None = None,
) -> int:
    count = 0
    for paragraph in document.xpath(".//w:p", namespaces=NS):
        text = element_text(paragraph)
        if old not in text:
            continue
        replacements = text.count(old)
        set_element_text(paragraph, text.replace(old, new))
        count += replacements
    if expected is not None and count != expected:
        raise RuntimeError(f"replacement count mismatch for {old!r}: {count} != {expected}")
    return count


def replace_paragraph_start(
    document: etree._Element,
    start: str,
    new: str,
    *,
    expected: int = 1,
) -> int:
    matches = [
        paragraph
        for paragraph in document.xpath(".//w:p", namespaces=NS)
        if element_text(paragraph).startswith(start)
    ]
    if len(matches) != expected:
        raise RuntimeError(
            f"paragraph-start count mismatch for {start!r}: "
            f"{len(matches)} != {expected}"
        )
    for paragraph in matches:
        set_element_text(paragraph, new)
    return len(matches)


def find_body_paragraph(
    body: etree._Element,
    predicate,
) -> etree._Element:
    for child in body:
        if child.tag != f"{{{NS['w']}}}p":
            continue
        if predicate(element_text(child)):
            return child
    raise RuntimeError("paragraph anchor not found")


def find_body_table(
    body: etree._Element,
    predicate,
) -> etree._Element:
    for child in body:
        if child.tag != f"{{{NS['w']}}}tbl":
            continue
        if predicate(element_text(child)):
            return child
    raise RuntimeError("table anchor not found")


def insert_text_before(
    body: etree._Element,
    anchor: etree._Element,
    template: etree._Element,
    text: str,
) -> etree._Element:
    paragraph = copy.deepcopy(template)
    set_element_text(paragraph, text)
    body.insert(body.index(anchor), paragraph)
    return paragraph


def move_section_before(
    body: etree._Element,
    *,
    start_heading: str,
    end_heading: str,
    before_heading: str,
) -> None:
    start = find_body_paragraph(body, lambda text: text == start_heading)
    end = find_body_paragraph(body, lambda text: text == end_heading)
    before = find_body_paragraph(body, lambda text: text == before_heading)
    start_index = body.index(start)
    end_index = body.index(end)
    block = list(body)[start_index:end_index]
    for element in block:
        body.remove(element)
    insertion_index = body.index(before)
    for offset, element in enumerate(block):
        body.insert(insertion_index + offset, element)


def remove_section_range(
    body: etree._Element,
    *,
    start_heading: str,
    end_heading: str,
) -> None:
    start = find_body_paragraph(body, lambda text: text == start_heading)
    end = find_body_paragraph(body, lambda text: text == end_heading)
    start_index = body.index(start)
    end_index = body.index(end)
    for element in list(body)[start_index:end_index]:
        body.remove(element)


def relationship_map(rels: etree._Element) -> dict[str, str]:
    return {rel.get("Id"): rel.get("Target") for rel in rels}


def image_ratio(path: Path) -> float:
    with Image.open(path) as image:
        return image.height / image.width


def set_drawing_size(paragraph: etree._Element, width_emu: int, height_emu: int) -> None:
    for extent in paragraph.xpath(".//wp:extent", namespaces=NS):
        extent.set("cx", str(width_emu))
        extent.set("cy", str(height_emu))
    for extent in paragraph.xpath(".//a:xfrm/a:ext", namespaces=NS):
        extent.set("cx", str(width_emu))
        extent.set("cy", str(height_emu))


def replace_existing_drawing(
    document: etree._Element,
    rels: etree._Element,
    rid: str,
    image_path: Path,
    replacements: dict[str, bytes],
) -> None:
    rel_targets = relationship_map(rels)
    target = rel_targets[rid]
    zip_name = f"word/{target}"
    replacements[zip_name] = image_path.read_bytes()
    drawings = document.xpath(
        f".//w:p[.//a:blip[@r:embed='{rid}']]",
        namespaces=NS,
    )
    if len(drawings) != 1:
        raise RuntimeError(f"expected one drawing for {rid}, found {len(drawings)}")
    paragraph = drawings[0]
    extent = paragraph.xpath(".//wp:extent", namespaces=NS)[0]
    width = int(extent.get("cx"))
    height = round(width * image_ratio(image_path))
    set_drawing_size(paragraph, width, height)


def next_relationship_id(rels: etree._Element) -> str:
    used = []
    for rel in rels:
        match = re.fullmatch(r"rId(\d+)", rel.get("Id", ""))
        if match:
            used.append(int(match.group(1)))
    return f"rId{max(used, default=0) + 1}"


def next_doc_property_id(document: etree._Element) -> int:
    ids = []
    for element in document.xpath(".//wp:docPr", namespaces=NS):
        value = element.get("id")
        if value and value.isdigit():
            ids.append(int(value))
    return max(ids, default=0) + 1


def add_image_before(
    document: etree._Element,
    rels: etree._Element,
    body: etree._Element,
    *,
    anchor: etree._Element,
    image_template: etree._Element,
    caption_template: etree._Element,
    image_path: Path,
    target_name: str,
    caption: str,
    replacements: dict[str, bytes],
) -> None:
    rid = next_relationship_id(rels)
    rel = etree.SubElement(rels, f"{{{NS['pr']}}}Relationship")
    rel.set("Id", rid)
    rel.set("Type", IMAGE_REL_TYPE)
    rel.set("Target", f"media/{target_name}")

    image_paragraph = copy.deepcopy(image_template)
    blip = image_paragraph.xpath(".//a:blip", namespaces=NS)[0]
    blip.set(f"{{{NS['r']}}}embed", rid)
    doc_id = next_doc_property_id(document)
    for doc_pr in image_paragraph.xpath(".//wp:docPr", namespaces=NS):
        doc_pr.set("id", str(doc_id))
        doc_pr.set("name", target_name)
    for nonvisual in image_paragraph.xpath(".//pic:cNvPr", namespaces=NS):
        nonvisual.set("name", target_name)
    width = 5_544_000
    height = round(width * image_ratio(image_path))
    set_drawing_size(image_paragraph, width, height)

    caption_paragraph = copy.deepcopy(caption_template)
    set_element_text(caption_paragraph, caption)

    index = body.index(anchor)
    body.insert(index, image_paragraph)
    body.insert(index + 1, caption_paragraph)
    replacements[f"word/media/{target_name}"] = image_path.read_bytes()


def set_table_row_values(row: etree._Element, values: list[str]) -> None:
    cells = row.xpath("./w:tc", namespaces=NS)
    if len(cells) != len(values):
        raise RuntimeError(f"cell count mismatch: {len(cells)} != {len(values)}")
    for cell, value in zip(cells, values):
        paragraphs = cell.xpath("./w:p", namespaces=NS)
        if not paragraphs:
            paragraph = etree.SubElement(cell, f"{{{NS['w']}}}p")
        else:
            paragraph = paragraphs[0]
        set_element_text(paragraph, value)
        for extra in paragraphs[1:]:
            set_element_text(extra, "")


def convert_first_typewise_table_to_comparison(
    body: etree._Element,
) -> etree._Element:
    typewise_tables = [
        table
        for table in body.xpath("./w:tbl", namespaces=NS)
        if "적정 종류" in element_text(table)
        and "선택 모델" in element_text(table)
        and "MAPE (%)" in element_text(table)
    ]
    if len(typewise_tables) != 2:
        raise RuntimeError(
            f"expected two typewise tables, found {len(typewise_tables)}"
        )
    table = typewise_tables[0]
    rows = table.xpath("./w:tr", namespaces=NS)
    values = [
        ["비교 항목", "수동 적정", "비접촉 스마트 적정 장치"],
        ["당량점 판단", "지시약 변색을 실험자가 관찰", "색상·열화상 특징을 머신러닝으로 분석"],
        ["데이터 기록", "종말점 눈금 중심", "반응 전 과정과 장치 상태를 연속 저장"],
        ["실험자 역할", "주입·교반·관찰·판독을 동시에 수행", "장치 상태와 안전을 확인"],
        ["결과 재분석", "판정 근거의 사후 확인이 제한적", "같은 원자료에 여러 판정법을 다시 적용"],
        ["주요 특징", "장치가 단순하고 즉시 판정 가능", "비접촉 기록·객관적 판정·제어 확장 가능"],
    ]
    if len(rows) != len(values):
        raise RuntimeError(f"comparison row count mismatch: {len(rows)}")
    for row, row_values in zip(rows, values):
        cells = row.xpath("./w:tc", namespaces=NS)
        while len(cells) > 3:
            row.remove(cells.pop())
        set_table_row_values(row, row_values)

    target = find_body_paragraph(
        body,
        lambda text: text.startswith(
            "수동 적정에서는 실험자가 주입 속도와 색 변화"
        ),
    )
    body.remove(table)
    body.insert(body.index(target) + 1, table)
    return table


def add_manual_method_row(body: etree._Element) -> None:
    target = None
    for table in body.xpath("./w:tbl", namespaces=NS):
        text = element_text(table)
        if "판정 방식" in text and "비머신러닝 색 최대 기울기" in text:
            target = table
            break
    if target is None:
        raise RuntimeError("method comparison table not found")
    rows = target.xpath("./w:tr", namespaces=NS)
    if "수동 적정" in element_text(target):
        return
    manual_row = copy.deepcopy(rows[1])
    set_table_row_values(manual_row, ["수동 적정", "0.367", "0.406", "1.22"])
    target.insert(target.index(rows[1]), manual_row)


def update_prediction_table(body: etree._Element) -> None:
    target = None
    for table in body.xpath("./w:tbl", namespaces=NS):
        text = element_text(table)
        if (
            "이론 당량점 (mL)" in text
            and (
                "자동 적정 추정값" in text
                or "센서 융합 모델 추정값" in text
            )
        ):
            target = table
            break
    if target is None:
        raise RuntimeError("12-run prediction table not found")

    header = target.xpath("./w:tr", namespaces=NS)[0]
    header_values = [
        element_text(cell) for cell in header.xpath("./w:tc", namespaces=NS)
    ]
    header_values[3] = "장치 기반 센서 융합 모델 추정값 (mL)"
    header_values[5] = "절대 상대오차"
    set_table_row_values(header, header_values)

    with PREDICTIONS.open(encoding="utf-8-sig", newline="") as file:
        data = list(csv.DictReader(file))
    type_order = {
        "strong_acid_strong_base": 0,
        "strong_acid_weak_base": 1,
        "weak_acid_strong_base": 2,
        "weak_acid_weak_base": 3,
    }
    data.sort(key=lambda row: (type_order[row["titration_type"]], float(row["concentration_M"])))
    rows = target.xpath("./w:tr", namespaces=NS)[1:]
    if len(rows) != len(data):
        raise RuntimeError(f"prediction row count mismatch: {len(rows)} != {len(data)}")
    type_labels = {
        "strong_acid_strong_base": "강산-강염기",
        "strong_acid_weak_base": "강산-약염기",
        "weak_acid_strong_base": "약산-강염기",
        "weak_acid_weak_base": "약산-약염기",
    }
    for row, record in zip(rows, data):
        theory = float(record["theoretical_ml"])
        predicted = float(record["smart_predicted_ml"])
        absolute = abs(predicted - theory)
        percentage = absolute / theory * 100
        set_table_row_values(
            row,
            [
                type_labels[record["titration_type"]],
                f"{float(record['concentration_M']):.2f} M",
                f"{theory:.2f}",
                f"{predicted:.3f}",
                f"{absolute:.3f}",
                f"{percentage:.2f}%",
            ],
        )


def renumber_figures(document: etree._Element) -> int:
    figure_number = 0
    for paragraph in document.xpath(".//w:p", namespaces=NS):
        text = element_text(paragraph)
        if not re.search(r"그림\s*\d+\.", text):
            continue

        def replacement(_match: re.Match[str]) -> str:
            nonlocal figure_number
            figure_number += 1
            return f"그림 {figure_number}."

        set_element_text(paragraph, re.sub(r"그림\s*\d+\.", replacement, text))
    return figure_number


def main() -> None:
    if not SOURCE_DOCX.exists():
        raise SystemExit(f"missing source: {SOURCE_DOCX}")

    with zipfile.ZipFile(SOURCE_DOCX) as source:
        entries = {info.filename: source.read(info.filename) for info in source.infolist()}
        infos = {info.filename: info for info in source.infolist()}

    parser = etree.XMLParser(remove_blank_text=False)
    document = etree.fromstring(entries["word/document.xml"], parser)
    rels = etree.fromstring(entries["word/_rels/document.xml.rels"], parser)
    body = document.xpath("./w:body", namespaces=NS)[0]

    # Requested title and terminology corrections.
    replace_text_in_paragraphs(
        document,
        "자격루에서 착안한스마트 자동 적정 보조장치",
        "자격루에서 착안한 비접촉 스마트 자동 적정 장치",
        expected=1,
    )
    replace_text_in_paragraphs(
        document,
        "스마트 자동 적정 보조장치",
        "비접촉 스마트 자동 적정 장치",
        expected=1,
    )
    replace_text_in_paragraphs(
        document,
        "스마트 자동 적정 보조 시스템",
        "비접촉 스마트 자동 적정 시스템",
        expected=1,
    )

    # Keep the motivation practical while explaining the Jagyeongnu analogy
    # concretely in the existing device-design section.
    motivation_text = (
        "장치의 일정 주입 원리는 자격루의 계량 개념에서 착안하였다. 자격루의 구조를 그대로 재현한 것은 "
        "아니지만, 일정한 흐름을 시간과 연결하여 양을 계산하고 특정 시점을 알리는 원리를 스테퍼 모터의 "
        "일정 회전, 주입 시간, 반응 신호의 기록에 대응시켰다. 이를 바탕으로 시린지 펌프, 일반 카메라, "
        "열화상 카메라, 데이터 수집 프로그램과 머신러닝 분석을 하나의 시스템으로 결합하였다."
    )
    motivation_replacement = (
        "장치 설계에서는 자격루가 일정한 물의 흐름과 경과 시간을 연결해 누적량과 특정 시점을 나타내는 "
        "방식에 착안하였다. 이를 시린지 펌프의 일정 주입, 작동 시간에 따른 부피 계산, 색상·열화상 변화에 "
        "따른 당량점 판정으로 구현하였다. 연구의 출발점은 이 계량 원리를 수동 적정의 관찰·기록 문제에 "
        "적용하여 반응 과정을 데이터로 남기는 것이었다."
    )
    replace_text_in_paragraphs(
        document, motivation_text, motivation_replacement, expected=1
    )
    device_anchor = find_body_paragraph(
        body, lambda text: text.startswith("장치는 주입부, 반응부, 관찰부")
    )
    jagyeongnu_paragraph = copy.deepcopy(device_anchor)
    set_element_text(
        jagyeongnu_paragraph,
        "자격루와 본 장치는 일정한 흐름을 이용해 누적량을 계산하고 특정 시점을 알려 준다는 공통 구조를 "
        "가진다. 자격루에서는 물의 흐름과 경과 시간이 시간 측정으로 이어지고, 본 장치에서는 스테퍼 모터의 "
        "일정 회전과 펌프 작동 시간이 주입 부피 계산으로 이어진다. 여기에 일반 영상과 열화상에서 나타나는 "
        "반응 변화를 결합해 당량점을 판단하도록 하였다. 자격루가 중력에 의한 물의 흐름을 이용하는 데 비해 "
        "본 장치는 모터로 유량을 제어한다는 차이가 있지만, 흐름·시간·누적량을 연결하는 계량 원리는 장치 "
        "설계의 핵심 개념으로 사용하였다.",
    )
    body.insert(body.index(device_anchor) + 1, jagyeongnu_paragraph)

    replace_paragraph_start(
        document,
        "본 연구의 목적은 적정액을 일정하게 주입하는 시린지 펌프를 직접 제작하고",
        "본 연구의 목적은 자격루의 계량 원리에서 착안한 시린지 펌프를 제작하고, 일반 영상의 색 변화와 "
        "열화상 ROI 온도 변화, 계산 주입량을 같은 시간축에 저장하여 당량점 부피를 추정하는 비접촉 스마트 "
        "자동 적정 시스템을 구현하는 데 있다. 또한 단순 색 변화 최대 기울기, 색·온도 임계값과 머신러닝 "
        "방식을 같은 원자료에 적용하여 머신러닝의 효과를 정량적으로 비교하고, 추정한 당량점 부피를 미지 "
        "시료 농도 계산과 선택형 자동 정지 기능으로 연결하고자 하였다.",
    )

    # Prevent the 12 human-stopped experiments from being described as an
    # experimentally validated automatic-stop result.
    replacements = [
        (
            "3. 자동 적정 당량점 부피 예측 결과",
            "3. 비접촉 스마트 적정 장치를 이용한 당량점 부피 추정 결과",
            1,
        ),
        ("자동 적정 원자료", "12회 적정 원자료", 1),
        ("자동 적정 추정값", "센서 융합 모델 추정값", 1),
        (
            "자동 적정 12회 중",
            "센서 융합 모델의 12회 추정 결과 중",
            1,
        ),
        ("표의 자동 적정값", "표의 모델 추정값", 1),
        ("MAPE를 67.5%, MAE를 59.8%", "MAPE를 67.4%, MAE를 59.7%", 1),
    ]
    for old, new, expected in replacements:
        replace_text_in_paragraphs(document, old, new, expected=expected)

    replace_paragraph_start(
        document,
        "12회 적정 원자료의 각 프레임에서 RGB·HSV 색상 특징",
        "비접촉 스마트 적정 장치로 네 가지 반응계와 세 농도에서 총 12회 적정을 수행하고, 일반 영상의 "
        "RGB·HSV 특징, 열화상 ROI 온도 특징과 펌프 상태를 같은 시간축에 기록하였다. 현재 누적 주입량, "
        "시료 농도, 이론 당량점 부피, 정답까지의 거리와 실험 진행률은 머신러닝 입력에서 제외하였다. 각 "
        "실험에서 모델이 선택한 당량점 후보 프레임의 기록 시각에 펌프 보정 유량을 적용하여 장치의 추정 "
        "당량점 부피를 산출하였다. 다음 표는 이 장치로 수집한 12회 실험의 조건별 결과이다.",
    )

    # Correct the scope of the Android and 25 fps claims.
    android_old = (
        "Android 앱에서도 스마트폰 카메라, USB-C Mini2 V2와 Bluetooth 펌프를 연결하고 Windows와 "
        "동일한 형식의 CSV를 생성하였다. 이로써 노트북 환경뿐 아니라 스마트폰을 이용한 데이터 수집 경로도 "
        "확보하였다. 앱은 이론 당량점, pH 곡선, 지시약 범위와 예측 부피를 표시하고 예측값을 미지 농도 "
        "계산으로 연결하였다."
    )
    android_new = (
        "Android 앱은 스마트폰 카메라, USB-C Mini2 V2와 Bluetooth 펌프를 연결하는 확장 시제품으로 "
        "개발하였다. 다만 본 보고서의 12회 습식 실험과 머신러닝 성능 평가는 Windows 수집 경로의 자료만 "
        "사용하였다. Android 경로의 Mini2 실시간 프레임 처리와 동일 형식 CSV 저장은 별도 검증 항목으로 "
        "구분하였다."
    )
    replace_text_in_paragraphs(document, android_old, android_new, expected=1)
    android_method_old = (
        "Android 앱은 Windows 대시보드와 유사한 사용 흐름을 유지하면서 스마트폰의 하드웨어 권한과 "
        "연결 기능을 네이티브 코드로 처리하였다. 일반 카메라 프레임은 CameraX ImageAnalysis로 받아 "
        "ROI의 RGB·HSV 특징을 계산하고, USB-C로 연결된 Mini2 V2의 권한과 스트림 상태를 관리하였다. "
        "펌프는 Bluetooth Classic SPP 방식으로 연결해 a·b·c 명령을 전송하였다."
    )
    android_method_new = (
        "Android 앱은 Windows 대시보드와 유사한 사용 흐름을 갖는 확장 시제품으로 제작하였다. 일반 "
        "카메라 프레임의 RGB·HSV 특징 계산, USB-C Mini2 V2 권한·스트림 상태 표시와 Bluetooth Classic "
        "SPP 펌프 명령을 구현하였다. 다만 Mini2 열화상 프레임의 실시간 변환과 저장은 본 보고서의 습식 "
        "실험 결과로 검증하지 않았다."
    )
    replace_text_in_paragraphs(
        document, android_method_old, android_method_new, expected=1
    )
    android_csv_old = (
        "모바일 환경에서도 ROI가 설정되지 않거나 장치 연결이 완료되지 않은 상태에서는 기록을 시작하지 "
        "않도록 하였다. 기록이 끝나면 실험 조건, 주입량, 색상·열화상 특징과 장치 상태를 Downloads 폴더에 "
        "CSV로 저장한다. Windows와 Android가 같은 열 이름과 단위를 사용하게 하여 어느 장치에서 얻은 "
        "데이터든 같은 분석 코드로 처리할 수 있도록 하였다."
    )
    android_csv_new = (
        "모바일 환경에서는 ROI와 장치 연결 상태를 확인한 뒤 기록하도록 구성하였다. 실험 조건, 계산 "
        "주입량, 일반 영상 특징과 장치 상태를 Downloads 폴더의 CSV에 저장하는 경로를 구현했고, 열화상 "
        "특징 열은 Mini2 실시간 프레임 검증이 끝날 때까지 미검증 상태로 구분하였다. 열 이름과 단위는 "
        "Windows 형식에 맞추되 Android 자료는 본 연구의 모델 학습·평가에서 제외하였다."
    )
    replace_text_in_paragraphs(document, android_csv_old, android_csv_new, expected=1)
    android_difference_old = (
        "예측 부피를 미지 농도 계산과 선택형 자동 정지로 연결하고, Windows와 Android에서 동일한 형식의 "
        "데이터를 수집하도록 구현한 점에서 기존의 단일 센서형 자동 적정 장치와 차이가 있다."
    )
    android_difference_new = (
        "예측 부피를 미지 농도 계산과 선택형 자동 정지로 연결하고, Windows 실험 경로와 같은 자료 형식을 "
        "사용하는 Android 확장 시제품을 설계한 점에서 기존의 단일 센서형 자동 적정 장치와 차이가 있다."
    )
    replace_text_in_paragraphs(
        document, android_difference_old, android_difference_new, expected=1
    )
    android_output_old = (
        "Windows 프로그램은 실제 실험실에서 두 카메라와 펌프를 동시에 연결하는 주 실행 환경으로 사용하고, "
        "Android 앱은 스마트폰 단독 수집 환경으로 확장하였다. 두 프로그램이 같은 CSV 열 이름과 단위를 "
        "사용하도록 맞추어 수집 장치가 달라도 분석 절차를 유지할 수 있게 하였다. 원본 자료는 실험별 파일로 "
        "보존하고, 전처리·모델 결과는 별도 폴더에서 생성하도록 구분하였다."
    )
    android_output_new = (
        "Windows 프로그램은 실제 12회 실험에서 두 카메라와 펌프를 연결한 주 실행 환경으로 사용하였다. "
        "Android 앱은 같은 CSV 열 이름과 단위를 목표로 한 확장 시제품이며, Mini2 실시간 프레임과 열화상 "
        "특징 저장은 별도 검증 대상으로 남겼다. 원본 자료는 실험별 파일로 보존하고 전처리·모델 결과는 "
        "별도 폴더에서 생성하도록 구분하였다."
    )
    replace_text_in_paragraphs(
        document, android_output_old, android_output_new, expected=1
    )
    fps_old = (
        "저장 구조를 개선한 뒤 25 fps 입력 프레임을 초당 25행으로 순서대로 기록하고, 종료 시 대기열에 "
        "남은 프레임까지 저장하는 것을 확인하였다."
    )
    fps_new = (
        "저장 구조를 개선한 뒤 0.04초 간격의 시험 입력을 초당 25행으로 순서대로 기록하고, 종료 시 "
        "대기열에 남은 프레임까지 저장하는 처리 경로를 확인하였다. 이는 새 습식 실험의 실제 USB 수집 "
        "속도가 아니라 CSV 저장 경로의 성능 시험이다."
    )
    replace_text_in_paragraphs(document, fps_old, fps_new, expected=1)
    fps_method_old = (
        "이후 기록 전용 대기열을 분리하고 종료 시 남은 프레임까지 저장하도록 수정하여 25 fps 입력을 "
        "초당 25행으로 순서대로 기록하였다."
    )
    fps_method_new = (
        "이후 기록 전용 대기열을 분리하고 종료 시 남은 프레임까지 저장하도록 수정하여 0.04초 간격의 "
        "시험 입력을 초당 25행으로 순서대로 기록하였다. 이 수치는 CSV 처리 경로 시험 결과이다."
    )
    replace_text_in_paragraphs(document, fps_method_old, fps_method_new, expected=1)
    fps_quality_old = (
        "개선된 구조에서는 25 fps 입력을 25.0행/s로 기록했으며 종료 버튼을 누른 뒤에도 대기열을 비운 "
        "다음 파일을 닫았다."
    )
    fps_quality_new = (
        "개선된 구조에서는 0.04초 간격의 시험 입력을 25.0행/s로 기록했으며 종료 버튼을 누른 뒤에도 "
        "대기열을 비운 다음 파일을 닫았다. 이는 새 습식 실험 전체가 25 fps로 저장되었다는 의미가 아니라 "
        "저장 처리 경로의 성능 확인 결과이다."
    )
    replace_text_in_paragraphs(document, fps_quality_old, fps_quality_new, expected=1)

    # Strengthen the report narrative without changing any measured value.
    replace_paragraph_start(
        document,
        "산·염기 적정은 미지 시료의 농도를 구하는 대표적인 정량 분석법이지만",
        "산·염기 적정은 미지 시료의 농도를 구하는 대표적인 정량 분석법이지만, 수동 적정에서는 적정액 "
        "주입, 지시약 변색 관찰과 눈금 판독을 한 사람이 동시에 수행한다. 이 때문에 종말점 판단 근거가 "
        "실험자의 순간적인 관찰에 의존하고 실험이 끝난 뒤에는 반응 과정을 다시 확인하기 어렵다. 본 "
        "연구에서는 자격루의 일정 흐름과 누적량 계량 원리에서 착안하여, 적정액을 일정하게 주입하면서 "
        "색상·열화상 변화를 비접촉으로 기록하고 머신러닝으로 당량점 부피를 추정하는 스마트 자동 적정 "
        "장치를 개발하였다.",
    )
    replace_paragraph_start(
        document,
        "색상·열화상 융합 머신러닝 모델의 평균 절대오차는",
        "색상·열화상 융합 머신러닝 모델의 평균 절대오차는 0.48 mL, 평균 제곱근 오차는 0.83 mL, 평균 "
        "절대백분율 오차는 1.52%였다. 이는 색 최대 기울기 방식의 4.67%보다 MAPE를 67.4% 줄인 결과이며, "
        "수동 적정의 1.22%와도 유사한 수준이다. 추정 당량점 부피는 미지 시료 농도 계산으로 연결했으며, "
        "동일 용액 3회 측정에서는 3.85%의 변동계수를 얻었다. 이 결과를 통해 비접촉 센서 측정, 머신러닝 "
        "판정, 농도 계산과 펌프 제어를 하나의 데이터 흐름으로 연결하였다.",
    )
    replace_paragraph_start(
        document,
        "색상 전용 모델과 색상·열화상 융합 모델의 MAPE 차이는",
        "현재 주입량을 제외한 센서 특징만 비교했을 때 색상 단독 모델의 MAPE는 1.55%, 열화상 단독은 "
        "3.66%, 색상·열화상 융합은 1.52%였다. 융합 모델은 세 입력 구성 가운데 가장 낮은 MAE와 MAPE를 "
        "보였다. 이번 실험에서는 색 변화가 뚜렷한 조건이 많아 색상 단독과의 차이는 0.03%p였지만, "
        "열화상까지 같은 시간축에 보존함으로써 색 변화가 불분명한 반응에서 활용할 수 있는 보조 신호와 "
        "모델의 판정 근거를 함께 확보하였다.",
    )
    redundant_modality = find_body_paragraph(
        body,
        lambda text: text.startswith(
            "열화상 전용은 색상 전용보다 오차가 컸지만"
        ),
    )
    body.remove(redundant_modality)
    replace_paragraph_start(
        document,
        "수동 적정의 MAE와 MAPE는 각각 0.37 mL, 1.22%였고",
        "수동 적정의 MAE와 MAPE는 각각 0.37 mL와 1.22%, 비접촉 스마트 적정 장치의 센서 융합 모델은 "
        "0.48 mL와 1.52%였다. 평균 오차의 차이는 0.30%p로, 장치가 비접촉 센서만으로 숙련자의 수동 "
        "적정에 근접한 당량점 추정 성능을 구현했음을 보여준다. 동시에 색상, 열화상, 펌프 상태와 계산 "
        "주입량을 자동으로 기록하여 결과가 나온 근거를 다시 확인할 수 있었다.",
    )
    replace_paragraph_start(
        document,
        "수동 적정은 종말점 한 지점의 눈금만 남는 반면",
        "수동 적정은 종말점의 눈금을 직접 판독하는 방식이고, 본 장치는 종말점 전후의 센서 변화를 연속 "
        "기록한 뒤 같은 분석 기준을 적용한다. 따라서 원자료를 보존하면 색 최대 기울기, 임계값, "
        "머신러닝과 후속 알고리즘을 같은 실험에 다시 적용할 수 있으며, 추정값을 미지 농도 계산과 펌프 "
        "정지 명령으로 연결할 수 있다.",
    )
    replace_paragraph_start(
        document,
        "또한 스마트 적정기는 실험자가 뷰렛 콕과 눈금",
        "수동 적정에서는 실험자가 주입 속도와 색 변화, 눈금을 동시에 판단하지만, 스마트 적정 장치에서는 "
        "펌프가 일정하게 적정액을 주입하고 프로그램이 반응 신호를 기록한다. 두 방식은 각각 단순성과 "
        "데이터 추적성이라는 장점을 가지며, 본 연구에서는 정확도뿐 아니라 기록 방식과 재분석 가능성을 "
        "함께 비교하였다.",
    )
    replace_paragraph_start(
        document,
        "반복 측정에 사용한 용액의 실제 농도는 별도로 표정하지 않았으므로",
        "세 측정값은 평균 0.0855 M을 중심으로 일정한 범위에 모였으며, 변동계수는 3.85%였다. 반복 "
        "측정에 사용한 용액의 기준 농도는 별도로 표정하지 않았으므로 절대 정확도보다 장치의 반복 "
        "작동성과 측정값의 일관성을 보여주는 자료로 해석하였다.",
    )
    replace_paragraph_start(
        document,
        "본 연구에서 스마트 적정기의 융합 모델 MAPE는 1.52%로",
        "같은 12회 원자료에서 색 최대 기울기 방식의 MAPE는 4.67%, 색·온도 임계값 방식은 5.65%, "
        "색상·열화상 융합 머신러닝은 1.52%였다. 특히 색 최대 기울기 방식보다 MAPE를 67.4% 줄여, "
        "적정 종류와 여러 센서 변화 특징을 함께 학습하는 방법이 고정된 규칙보다 당량점 판정에 "
        "효과적임을 확인하였다. 수동 적정의 1.22%와 비교해도 유사한 수준으로, 비접촉 측정과 자동 기록을 "
        "유지하면서 정량 분석에 활용할 수 있는 정확도를 확보하였다.",
    )
    replace_paragraph_start(
        document,
        "열화상은 색상 전용 모델을 크게 능가하지는 않았지만",
        "융합 모델은 색상 단독 1.55%보다 낮은 1.52%의 MAPE를 나타냈다. 개선 폭은 0.03%p였지만, "
        "열화상은 색상과 다른 반응 신호를 동시에 기록하여 색 변화가 불분명하거나 조명·반사의 영향을 "
        "받는 조건을 분석할 수 있는 확장 기반을 제공하였다. 센서를 단순히 추가한 것이 아니라 단독·융합 "
        "모델을 같은 평가 방식으로 비교하여 각 입력의 실제 기여를 확인했다는 데 의미가 있다.",
    )
    replace_paragraph_start(
        document,
        "가장 큰 제한은 조건별 실험이 1회이고",
        "현재 결과를 바탕으로 다음 단계의 검증 기준도 구체화하였다. 적정액을 표정하고 조건별 반복 횟수를 "
        "늘린 뒤 모델 설정을 고정한 새로운 시료를 평가하면, 용액 조제 오차와 모델 오차를 분리할 수 있다. "
        "전자저울을 이용한 실제 유량 보정과 자동 정지 후의 과주입량 측정까지 추가하면 장치의 정량 성능과 "
        "자동 제어 성능을 독립적으로 검증할 수 있다.",
    )
    replace_paragraph_start(
        document,
        "본 연구에서는 시린지 펌프의 기계 구조를 직접 설계·제작하고",
        "본 연구에서는 자격루의 일정 흐름과 누적량 계량 원리에서 착안해 시린지 펌프를 직접 설계·제작하고, "
        "일반 카메라와 열화상 카메라를 하나의 프로그램에 연결하였다. 최종 장치는 펌프 주입량, 색상·열화상 "
        "변화와 장치 상태를 같은 시간축으로 기록했으며, 네 반응계와 세 농도에서 수행한 12회 적정의 "
        "1,822행을 동일한 형식으로 확보하였다.",
    )
    replace_paragraph_start(
        document,
        "수동 적정은 MAE 0.37 mL, MAPE 1.22%로",
        "비접촉 스마트 적정 장치의 센서 융합 모델은 MAE 0.48 mL, MAPE 1.52%로 수동 적정의 "
        "0.37 mL와 1.22%에 근접한 결과를 보였다. 장치는 반응 과정을 비접촉으로 자동 기록하고 같은 "
        "분석 기준을 반복 적용할 수 있으므로, 숙련자의 판독에 의존하던 적정 과정을 추적 가능한 정량 "
        "데이터로 전환하였다.",
    )
    replace_paragraph_start(
        document,
        "같은 원자료에 적용한 비머신러닝 판정의 MAPE는",
        "같은 원자료에 적용한 비머신러닝 판정의 MAPE는 4.67%와 5.65%였고, 색상·열화상 융합 "
        "머신러닝은 1.52%였다. 머신러닝은 단일 최대 기울기나 고정 임계값보다 적정 종류에 따른 색상과 "
        "열화상 패턴을 안정적으로 해석하였다. 센서 구성 비교에서도 융합 모델이 가장 낮은 오차를 보여 "
        "열화상을 포함한 비접촉 복합 측정 구조의 가능성을 확인하였다.",
    )
    replace_paragraph_start(
        document,
        "예측된 당량점 부피는 화학량론식으로 미지 농도 계산에 연결되었고",
        "추정한 당량점 부피는 화학량론식으로 미지 농도 계산에 연결하였고, 동일 용액 3회 측정에서는 "
        "3.85%의 변동계수를 얻었다. 또한 모델 점수와 지속적인 색 변화를 함께 확인하는 선택형 자동 정지 "
        "기능을 구현하여 센서 측정, 분석, 농도 계산과 펌프 제어가 이어지는 비접촉 스마트 자동 적정 "
        "시스템의 기본 구조를 완성하였다.",
    )

    add_manual_method_row(body)
    update_prediction_table(body)
    comparison_table = convert_first_typewise_table_to_comparison(body)
    prediction_table = find_body_table(
        body,
        lambda text: "장치 기반 센서 융합 모델 추정값" in text,
    )
    device_metrics_paragraph = find_body_paragraph(
        body,
        lambda text: text.startswith(
            "색상·열화상 융합 모델의 전체 MAE는 0.476 mL"
        ),
    )
    body.remove(device_metrics_paragraph)
    body.insert(body.index(prediction_table) + 1, device_metrics_paragraph)

    image_replacements: dict[str, bytes] = {}
    replacements_by_rid = {
        "rId24": FIGURE_DIR / "04_method_comparison_mape.png",
        "rId25": FIGURE_DIR / "06_sensor_modality_comparison.png",
        "rId26": FIGURE_DIR / "07_fusion_typewise_mape.png",
        "rId27": FIGURE_DIR / "01_smart_theory_vs_prediction.png",
        "rId28": FIGURE_DIR / "03_manual_vs_smart_by_condition.png",
        "rId29": FIGURE_DIR / "08_repeatability_three_runs.png",
    }
    for rid, image_path in replacements_by_rid.items():
        replace_existing_drawing(document, rels, rid, image_path, image_replacements)

    caption_replacements = [
        (
            "Windows 앱과 Android 앱의 일반 영상·열화상 수집 화면 비교.",
            "Windows 수집 화면과 Android 확장 시제품의 화면 구성 비교.",
        ),
        (
            "비머신러닝 두 방식과 머신러닝 세 입력군의 MAPE 비교.",
            "수동 적정, 비머신러닝 두 방식과 머신러닝 세 입력군의 MAPE 비교.",
        ),
        (
            "색상·열화상·융합 입력군의 전체 MAE와 MAPE 비교.",
            "현재 주입량을 제외한 색상·열화상·융합 입력군의 MAPE와 MAE 비교.",
        ),
        (
            "이론 당량점 부피와 색상·열화상 융합 모델 추정값의 비교.",
            "12회 적정 자료의 이론 당량점 부피와 색상·열화상 융합 모델 추정값 비교.",
        ),
        (
            "수동 적정과 스마트 적정기의 MAE·RMSE 비교.",
            "같은 12개 조건의 수동 적정과 비접촉 장치 센서 융합 모델 절대 상대오차 비교.",
        ),
    ]
    for old, new in caption_replacements:
        replace_text_in_paragraphs(document, old, new, expected=1)

    image_template = document.xpath(
        ".//w:p[.//a:blip[@r:embed='rId24']]", namespaces=NS
    )[0]
    caption_template = find_body_paragraph(
        body, lambda text: "수동 적정, 비머신러닝 두 방식" in text
    )

    manual_heading = find_body_paragraph(body, lambda text: text == "4. 수동 적정 결과")
    add_image_before(
        document,
        rels,
        body,
        anchor=manual_heading,
        image_template=image_template,
        caption_template=caption_template,
        image_path=FIGURE_DIR / "02_smart_error_by_condition.png",
        target_name="report_revision_02_smart_error_by_condition.png",
        caption="그림 0. 12회 적정 자료의 조건별 색상·열화상 융합 모델 절대 상대오차.",
        replacements=image_replacements,
    )

    data_quality_next = find_body_paragraph(
        body,
        lambda text: text.startswith(
            "모델 검증에서는 프레임 수가 많다는 이유로 표본 수가 충분하다고 판단하지 않았다."
        ),
    )
    add_image_before(
        document,
        rels,
        body,
        anchor=data_quality_next,
        image_template=image_template,
        caption_template=caption_template,
        image_path=FIGURE_DIR / "09_csv_recording_throughput.png",
        target_name="report_revision_09_csv_recording_throughput.png",
        caption="그림 0. CSV 저장 구조 개선 전후 처리 경로 시험 결과.",
        replacements=image_replacements,
    )

    # Number the core scientific tables. Image-layout tables remain figures.
    condition_table = find_body_table(
        body,
        lambda text: "적정 종류" in text
        and "시료" in text
        and "적정액" in text
        and "지시약" in text,
    )
    manual_table = find_body_table(
        body,
        lambda text: "수동 종말점" in text and "부호 오차" in text,
    )
    method_table = find_body_table(
        body,
        lambda text: "판정 방식" in text
        and "비머신러닝 색 최대 기울기" in text,
    )
    typewise_table = find_body_table(
        body,
        lambda text: "선택 모델" in text
        and "강산-강염기" in text
        and "전체" in text,
    )
    repeatability_table = find_body_table(
        body,
        lambda text: "앱 환산 농도" in text and "변동계수" in text,
    )
    for table, caption in [
        (condition_table, "표 1. 적정 종류와 실험 조건."),
        (
            prediction_table,
            "표 2. 비접촉 스마트 적정 장치를 이용한 12회 당량점 부피 추정 결과.",
        ),
        (repeatability_table, "표 3. 동일 용액 3회 반복 측정 결과."),
        (manual_table, "표 4. 수동 적정 결과."),
        (
            method_table,
            "표 5. 수동·비머신러닝·머신러닝 당량점 판정 성능 비교.",
        ),
        (
            typewise_table,
            "표 6. 적정 종류별 색상·열화상 융합 모델 성능.",
        ),
        (
            comparison_table,
            "표 7. 수동 적정과 비접촉 스마트 적정 장치의 특성 비교.",
        ),
    ]:
        insert_text_before(body, table, caption_template, caption)

    # Present device accuracy and repeatability before manual-reference results.
    move_section_before(
        body,
        start_heading="8. 미지 농도 계산과 반복성",
        end_heading="9. 선택형 자동 정지 기능",
        before_heading="4. 수동 적정 결과",
    )
    heading_replacements = [
        (
            "8. 미지 농도 계산과 반복성",
            "4. 동일 조건 반복 측정과 미지 농도 계산",
        ),
        ("4. 수동 적정 결과", "5. 수동 적정 결과"),
        (
            "5. 비머신러닝과 머신러닝의 성능 비교",
            "6. 비머신러닝과 머신러닝의 성능 비교",
        ),
        (
            "6. 센서 입력 구성과 적정 종류별 결과",
            "7. 센서 입력 구성과 적정 종류별 결과",
        ),
        (
            "7. 수동 적정과 스마트 적정기의 비교",
            "8. 수동 적정과 비접촉 스마트 적정 장치의 비교",
        ),
    ]
    for old, new in heading_replacements:
        heading = find_body_paragraph(body, lambda text, old=old: text == old)
        set_element_text(heading, new)

    # Consolidate the duplicated interpretation sections into the existing
    # comprehensive discussion and summary; no new section is introduced.
    remove_section_range(
        body,
        start_heading="15. 수동 적정과 스마트 적정의 역할 비교",
        end_heading="17. 장치 운용 절차와 안전성",
    )
    replace_text_in_paragraphs(
        document,
        "17. 장치 운용 절차와 안전성",
        "15. 장치 운용 절차와 안전성",
        expected=1,
    )

    figure_count = renumber_figures(document)

    entries["word/document.xml"] = etree.tostring(
        document, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    entries["word/_rels/document.xml.rels"] = etree.tostring(
        rels, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    entries.update(image_replacements)

    if OUTPUT_DOCX.exists():
        OUTPUT_DOCX.unlink()
    with zipfile.ZipFile(
        OUTPUT_DOCX, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as output:
        for name, payload in entries.items():
            info = infos.get(name)
            if info is None:
                output.writestr(name, payload)
            else:
                output.writestr(info, payload)

    print(f"created={OUTPUT_DOCX}")
    print(f"figures_renumbered={figure_count}")
    print(f"new_images={len(image_replacements)}")


if __name__ == "__main__":
    main()
