#!/usr/bin/env python3
"""Build a reviewable HWPX draft from the national science-fair Markdown report.

The builder intentionally uses only Python's standard library plus Pillow, which
is already used by the repository's report-asset tooling.  It reuses Form 6 from
the official 2026 National Science Fair forms and embeds every real image that is
already referenced by the Markdown.  Missing identity fields and three evidence
screenshots remain explicit placeholders; the script never fabricates them.

The result is an *automatic review draft*.  Hancom Office must still open and
save it once so line layout, page numbers, the table of contents, and the final
30-page limit can be checked in the official renderer.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import html
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = PROJECT_ROOT / "docs/official_forms/제72회_전국과학전람회_각종서식.hwpx"
DEFAULT_MARKDOWN = PROJECT_ROOT / "docs/science_fair_report_national_formatted.md"
DEFAULT_OUTPUT = PROJECT_ROOT / "docs/제72회_작품설명서_자동생성검토본.hwpx"
DEFAULT_PRIVACY_OUTPUT = PROJECT_ROOT / "docs/제72회_작품설명서_개인정보삭제_자동생성검토본.hwpx"

TITLE_LINE_1 = "색 변화·열화상·주입량 융합 기반"
TITLE_LINE_2 = "자동 적정 보조 시스템 개발"
TITLE = f"{TITLE_LINE_1} {TITLE_LINE_2}"

NS = {
    "ha": "http://www.hancom.co.kr/hwpml/2011/app",
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hp10": "http://www.hancom.co.kr/hwpml/2016/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hhs": "http://www.hancom.co.kr/hwpml/2011/history",
    "hm": "http://www.hancom.co.kr/hwpml/2011/master-page",
    "hpf": "http://www.hancom.co.kr/schema/2011/hpf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "opf": "http://www.idpf.org/2007/opf/",
    "ooxmlchart": "http://www.hancom.co.kr/hwpml/2016/ooxmlchart",
    "hwpunitchar": "http://www.hancom.co.kr/hwpml/2016/HwpUnitChar",
    "epub": "http://www.idpf.org/2007/ops",
    "config": "urn:oasis:names:tc:opendocument:xmlns:config:1.0",
}

for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

HP = f"{{{NS['hp']}}}"
HS = f"{{{NS['hs']}}}"
HC = f"{{{NS['hc']}}}"
HH = f"{{{NS['hh']}}}"
OPF = f"{{{NS['opf']}}}"

BODY_WIDTH = 48_190
BODY_CHAR_PR = "19"  # 11 pt Human Myeongjo in the official file.
HEADING_1_CHAR_PR = "2"  # 16 pt bold Human Myeongjo.
HEADING_2_CHAR_PR = "3"  # 14 pt bold Human Myeongjo.
HEADING_3_CHAR_PR = "4"  # 13 pt bold Human Myeongjo.
BODY_PARA_PR = "0"  # justified, 160% line spacing.
CENTER_PARA_PR = "26"

# Stable, current report-body markers that prove the generated HWPX contains
# required scientific sections without pinning obsolete exact sample-count claims.
REQUIRED_BODY_MARKERS = (
    "연구 요약",
    "적정 종류 조건부 센서 시계열 모델",
    "종말점 근처 미세 주입과 선택형 자동 정지",
    "생성형 AI 활용",
)


@dataclass(frozen=True)
class EmbeddedImage:
    source: Path
    item_id: str
    archive_path: str
    media_type: str
    width_px: int
    height_px: int


def _xml_bytes(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _plain_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("&nbsp;", " ")
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"\[([^]]+)\]\(([^)]+)\)", r"\1 (\2)", value)
    value = value.replace("**", "").replace("`", "")
    value = value.replace("  ", " ")
    return value.strip()


def _new_paragraph(
    text: str = "",
    *,
    char_pr: str = BODY_CHAR_PR,
    para_pr: str = BODY_PARA_PR,
    page_break: bool = False,
) -> ET.Element:
    paragraph = ET.Element(
        HP + "p",
        {
            "id": "2147483648",
            "paraPrIDRef": para_pr,
            "styleIDRef": "0",
            "pageBreak": "1" if page_break else "0",
            "columnBreak": "0",
            "merged": "0",
        },
    )
    run = ET.SubElement(paragraph, HP + "run", {"charPrIDRef": char_pr})
    if text:
        node = ET.SubElement(run, HP + "t")
        node.text = text
    return paragraph


def _set_paragraph_text(
    paragraph: ET.Element,
    text: str,
    *,
    char_pr: str | None = None,
    para_pr: str | None = None,
) -> None:
    for child in list(paragraph):
        if child.tag == HP + "run":
            paragraph.remove(child)
    insert_at = 0
    for index, child in enumerate(list(paragraph)):
        if child.tag == HP + "linesegarray":
            insert_at = index
            break
        insert_at = index + 1
    run = ET.Element(HP + "run", {"charPrIDRef": char_pr or BODY_CHAR_PR})
    node = ET.SubElement(run, HP + "t")
    node.text = text
    paragraph.insert(insert_at, run)
    if para_pr is not None:
        paragraph.set("paraPrIDRef", para_pr)


def _find_table(root: ET.Element, table_id: str) -> ET.Element:
    for table in root.iter(HP + "tbl"):
        if table.get("id") == table_id:
            return table
    raise ValueError(f"official Form 6 table not found: {table_id}")


def _fill_cover(cover: ET.Element, *, privacy_copy: bool) -> None:
    output_number_table = _find_table(cover, "1103204747")
    output_number_rows = output_number_table.findall(HP + "tr")
    output_number_cell = output_number_rows[1].find(HP + "tc")
    output_number_paragraph = output_number_cell.find(f"{HP}subList/{HP}p")
    _set_paragraph_text(output_number_paragraph, "[출품번호 입력]", char_pr=BODY_CHAR_PR, para_pr=CENTER_PARA_PR)

    outer_table = next(cover.iter(HP + "tbl"))
    outer_cell = outer_table.find(f"{HP}tr/{HP}tc")
    outer_sublist = outer_cell.find(HP + "subList")
    direct_paragraphs = [child for child in outer_sublist if child.tag == HP + "p"]
    _set_paragraph_text(direct_paragraphs[7], TITLE_LINE_1, char_pr=HEADING_1_CHAR_PR, para_pr=CENTER_PARA_PR)
    _set_paragraph_text(direct_paragraphs[8], TITLE_LINE_2, char_pr=HEADING_1_CHAR_PR, para_pr=CENTER_PARA_PR)

    info_table = _find_table(cover, "1103204750")
    info_values = [
        "" if privacy_copy else "[출품학생 입력]",
        "" if privacy_copy else "[지도교원 입력]",
        "학생부",
        "[지역대회 출품원서와 동일하게 입력]",
    ]
    for row, value in zip(info_table.findall(HP + "tr"), info_values):
        cells = row.findall(HP + "tc")
        value_paragraph = cells[1].find(f"{HP}subList/{HP}p")
        _set_paragraph_text(value_paragraph, value, char_pr=BODY_CHAR_PR, para_pr=CENTER_PARA_PR)


def _add_body_bold_style(header_root: ET.Element) -> str:
    char_properties = header_root.find(f".//{HH}charProperties")
    if char_properties is None:
        raise ValueError("official HWPX header has no character properties")
    existing = [int(item.get("id", "0")) for item in char_properties.findall(HH + "charPr")]
    new_id = str(max(existing) + 1)
    body = next(item for item in char_properties.findall(HH + "charPr") if item.get("id") == BODY_CHAR_PR)
    bold = copy.deepcopy(body)
    bold.set("id", new_id)
    if bold.find(HH + "bold") is None:
        underline = bold.find(HH + "underline")
        index = list(bold).index(underline) if underline is not None else len(bold)
        bold.insert(index, ET.Element(HH + "bold"))
    char_properties.append(bold)
    char_properties.set("itemCnt", str(len(char_properties.findall(HH + "charPr"))))
    return new_id


def _make_section_properties(template_section_root: ET.Element, *, body: bool) -> ET.Element:
    source = template_section_root[0]
    paragraph = copy.deepcopy(source)
    # The official section properties live inside the first run.  Clearing the
    # run itself would also delete page size, margins, numbering, and columns.
    for text_node in paragraph.iter(HP + "t"):
        text_node.text = ""
    paragraph.set("paraPrIDRef", BODY_PARA_PR)
    for run in paragraph.findall(HP + "run"):
        run.set("charPrIDRef", BODY_CHAR_PR)
    paragraph.set("pageBreak", "0")
    if body:
        page_pr = paragraph.find(f".//{HP}pagePr")
        margin = page_pr.find(HP + "margin") if page_pr is not None else None
        if margin is None:
            raise ValueError("official HWPX section has no page margin definition")
        margin.set("left", "5669")
        margin.set("right", "5669")
        margin.set("top", "4252")
        margin.set("bottom", "4252")
        margin.set("header", "2834")
        margin.set("footer", "2834")
    return paragraph


def _parse_markdown_tables(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    raw: list[list[str]] = []
    index = start
    while index < len(lines) and lines[index].lstrip().startswith("|"):
        cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
        raw.append(cells)
        index += 1
    if len(raw) >= 2 and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in raw[1]):
        raw.pop(1)
    return [[_plain_text(cell) for cell in row] for row in raw], index


def _column_widths(rows: list[list[str]]) -> list[int]:
    columns = max(len(row) for row in rows)
    weights: list[int] = []
    for column in range(columns):
        longest = max((len(row[column]) if column < len(row) else 0) for row in rows)
        weights.append(max(6, min(longest, 36)))
    total = sum(weights)
    widths = [max(2_800, round(BODY_WIDTH * weight / total)) for weight in weights]
    widths[-1] += BODY_WIDTH - sum(widths)
    return widths


def _new_table(rows: list[list[str]], *, table_id: int, bold_char_pr: str) -> ET.Element:
    widths = _column_widths(rows)
    columns = len(widths)
    row_height = 2_500
    paragraph = _new_paragraph()
    run = paragraph.find(HP + "run")
    table = ET.SubElement(
        run,
        HP + "tbl",
        {
            "id": str(table_id),
            "zOrder": str(table_id - 1_200_000_000),
            "numberingType": "TABLE",
            "textWrap": "TOP_AND_BOTTOM",
            "textFlow": "BOTH_SIDES",
            "lock": "0",
            "dropcapstyle": "None",
            "pageBreak": "CELL",
            "repeatHeader": "1",
            "rowCnt": str(len(rows)),
            "colCnt": str(columns),
            "cellSpacing": "0",
            "borderFillIDRef": "6",
            "noAdjust": "0",
        },
    )
    ET.SubElement(
        table,
        HP + "sz",
        {
            "width": str(BODY_WIDTH),
            "widthRelTo": "ABSOLUTE",
            "height": str(row_height * len(rows)),
            "heightRelTo": "ABSOLUTE",
            "protect": "0",
        },
    )
    ET.SubElement(
        table,
        HP + "pos",
        {
            "treatAsChar": "1",
            "affectLSpacing": "0",
            "flowWithText": "1",
            "allowOverlap": "0",
            "holdAnchorAndSO": "0",
            "vertRelTo": "PARA",
            "horzRelTo": "COLUMN",
            "vertAlign": "TOP",
            "horzAlign": "LEFT",
            "vertOffset": "0",
            "horzOffset": "0",
        },
    )
    ET.SubElement(table, HP + "outMargin", {"left": "0", "right": "0", "top": "140", "bottom": "140"})
    ET.SubElement(table, HP + "inMargin", {"left": "100", "right": "100", "top": "100", "bottom": "100"})
    for row_index, values in enumerate(rows):
        row = ET.SubElement(table, HP + "tr")
        for column_index, width in enumerate(widths):
            cell = ET.SubElement(
                row,
                HP + "tc",
                {
                    "name": "",
                    "header": "1" if row_index == 0 else "0",
                    "hasMargin": "0",
                    "protect": "0",
                    "editable": "0",
                    "dirty": "0",
                    "borderFillIDRef": "6",
                },
            )
            sublist = ET.SubElement(
                cell,
                HP + "subList",
                {
                    "id": "",
                    "textDirection": "HORIZONTAL",
                    "lineWrap": "BREAK",
                    "vertAlign": "CENTER",
                    "linkListIDRef": "0",
                    "linkListNextIDRef": "0",
                    "textWidth": "0",
                    "textHeight": "0",
                    "hasTextRef": "0",
                    "hasNumRef": "0",
                },
            )
            value = values[column_index] if column_index < len(values) else ""
            sublist.append(
                _new_paragraph(
                    value,
                    char_pr=bold_char_pr if row_index == 0 else BODY_CHAR_PR,
                    para_pr=CENTER_PARA_PR if row_index == 0 else BODY_PARA_PR,
                )
            )
            ET.SubElement(cell, HP + "cellAddr", {"colAddr": str(column_index), "rowAddr": str(row_index)})
            ET.SubElement(cell, HP + "cellSpan", {"colSpan": "1", "rowSpan": "1"})
            ET.SubElement(cell, HP + "cellSz", {"width": str(width), "height": str(row_height)})
            ET.SubElement(cell, HP + "cellMargin", {"left": "141", "right": "141", "top": "141", "bottom": "141"})
    ET.SubElement(run, HP + "t")
    return paragraph


def _media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".bmp":
        return "image/bmp"
    raise ValueError(f"unsupported report image: {path}")


def _new_picture(image: EmbeddedImage, *, picture_id: int) -> ET.Element:
    org_width = image.width_px * 72
    org_height = image.height_px * 72
    max_width = 44_000
    max_height = 30_000
    scale = min(max_width / org_width, max_height / org_height, 1.0)
    current_width = max(4_000, round(org_width * scale))
    current_height = max(3_000, round(org_height * scale))
    scale_x = current_width / org_width
    scale_y = current_height / org_height

    paragraph = _new_paragraph(para_pr=CENTER_PARA_PR)
    run = paragraph.find(HP + "run")
    picture = ET.SubElement(
        run,
        HP + "pic",
        {
            "id": str(picture_id),
            "zOrder": str(picture_id - 1_300_000_000),
            "numberingType": "PICTURE",
            "textWrap": "TOP_AND_BOTTOM",
            "textFlow": "BOTH_SIDES",
            "lock": "0",
            "dropcapstyle": "None",
            "href": "",
            "groupLevel": "0",
            "instid": str(picture_id),
            "reverse": "0",
        },
    )
    ET.SubElement(picture, HP + "offset", {"x": "0", "y": "0"})
    ET.SubElement(picture, HP + "orgSz", {"width": str(org_width), "height": str(org_height)})
    ET.SubElement(picture, HP + "curSz", {"width": str(current_width), "height": str(current_height)})
    ET.SubElement(picture, HP + "flip", {"horizontal": "0", "vertical": "0"})
    ET.SubElement(
        picture,
        HP + "rotationInfo",
        {"angle": "0", "centerX": str(current_width // 2), "centerY": str(current_height // 2), "rotateimage": "1"},
    )
    rendering = ET.SubElement(picture, HP + "renderingInfo")
    ET.SubElement(rendering, HC + "transMatrix", {"e1": "1", "e2": "0", "e3": "0", "e4": "0", "e5": "1", "e6": "0"})
    ET.SubElement(
        rendering,
        HC + "scaMatrix",
        {"e1": f"{scale_x:.6f}", "e2": "0", "e3": "0", "e4": "0", "e5": f"{scale_y:.6f}", "e6": "0"},
    )
    ET.SubElement(rendering, HC + "rotMatrix", {"e1": "1", "e2": "0", "e3": "0", "e4": "0", "e5": "1", "e6": "0"})
    ET.SubElement(
        picture,
        HC + "img",
        {"binaryItemIDRef": image.item_id, "bright": "0", "contrast": "0", "effect": "REAL_PIC", "alpha": "0"},
    )
    rect = ET.SubElement(picture, HP + "imgRect")
    ET.SubElement(rect, HC + "pt0", {"x": "0", "y": "0"})
    ET.SubElement(rect, HC + "pt1", {"x": str(org_width), "y": "0"})
    ET.SubElement(rect, HC + "pt2", {"x": str(org_width), "y": str(org_height)})
    ET.SubElement(rect, HC + "pt3", {"x": "0", "y": str(org_height)})
    ET.SubElement(picture, HP + "imgClip", {"left": "0", "right": str(org_width), "top": "0", "bottom": str(org_height)})
    ET.SubElement(picture, HP + "inMargin", {"left": "0", "right": "0", "top": "0", "bottom": "0"})
    ET.SubElement(picture, HP + "imgDim", {"dimwidth": str(org_width), "dimheight": str(org_height)})
    ET.SubElement(picture, HP + "effects")
    ET.SubElement(
        picture,
        HP + "sz",
        {
            "width": str(current_width),
            "widthRelTo": "ABSOLUTE",
            "height": str(current_height),
            "heightRelTo": "ABSOLUTE",
            "protect": "0",
        },
    )
    ET.SubElement(
        picture,
        HP + "pos",
        {
            "treatAsChar": "1",
            "affectLSpacing": "0",
            "flowWithText": "1",
            "allowOverlap": "0",
            "holdAnchorAndSO": "0",
            "vertRelTo": "PARA",
            "horzRelTo": "COLUMN",
            "vertAlign": "TOP",
            "horzAlign": "CENTER",
            "vertOffset": "0",
            "horzOffset": "0",
        },
    )
    ET.SubElement(picture, HP + "outMargin", {"left": "0", "right": "0", "top": "0", "bottom": "0"})
    comment = ET.SubElement(picture, HP + "shapeComment")
    comment.text = f"전국과학전람회 작품설명서에 문서 포함으로 삽입한 그림: {image.source.name}"
    ET.SubElement(run, HP + "t")
    return paragraph


def _extract_image_sources(markdown: str, markdown_path: Path) -> list[Path]:
    sources: list[Path] = []
    for relative in re.findall(r"!\[[^]]*\]\(([^)]+)\)", markdown):
        source = (markdown_path.parent / relative).resolve()
        if not source.exists():
            raise FileNotFoundError(f"report image does not exist: {source}")
        if source not in sources:
            sources.append(source)
    return sources


def _prepare_images(markdown: str, markdown_path: Path) -> list[EmbeddedImage]:
    result: list[EmbeddedImage] = []
    for index, source in enumerate(_extract_image_sources(markdown, markdown_path), start=1):
        with Image.open(source) as image:
            width, height = image.size
        suffix = ".jpg" if source.suffix.lower() == ".jpeg" else source.suffix.lower()
        result.append(
            EmbeddedImage(
                source=source,
                item_id=f"image{index}",
                archive_path=f"BinData/image{index}{suffix}",
                media_type=_media_type(source),
                width_px=width,
                height_px=height,
            )
        )
    return result


def _markdown_to_section(
    markdown: str,
    markdown_path: Path,
    template_section_root: ET.Element,
    images: list[EmbeddedImage],
    *,
    bold_char_pr: str,
) -> ET.Element:
    marker = "# 차례"
    if marker not in markdown:
        raise ValueError("national report Markdown has no contents heading")
    markdown = markdown[markdown.index(marker) :]
    lines = markdown.splitlines()
    section = ET.Element(HS + "sec")
    section.append(_make_section_properties(template_section_root, body=True))
    images_by_source = {item.source: item for item in images}
    image_counter = 0
    table_counter = 0
    top_heading_seen = False
    index = 0
    previous_blank = False
    while index < len(lines):
        raw = lines[index].rstrip()
        stripped = raw.strip()
        if not stripped:
            if not previous_blank:
                section.append(_new_paragraph())
            previous_blank = True
            index += 1
            continue
        previous_blank = False
        if stripped.startswith("<!--") or stripped.startswith("<div") or stripped == "</div>":
            index += 1
            continue
        if stripped == "---":
            index += 1
            continue
        if stripped.startswith("|"):
            rows, index = _parse_markdown_tables(lines, index)
            if rows:
                table_counter += 1
                section.append(_new_table(rows, table_id=1_200_000_000 + table_counter, bold_char_pr=bold_char_pr))
            continue
        image_match = re.fullmatch(r"!\[([^]]*)\]\(([^)]+)\)", stripped)
        if image_match:
            source = (markdown_path.parent / image_match.group(2)).resolve()
            image_counter += 1
            section.append(_new_picture(images_by_source[source], picture_id=1_300_000_000 + image_counter))
            index += 1
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            level = len(heading.group(1))
            text = _plain_text(heading.group(2))
            page_break = level == 1 and top_heading_seen
            if level == 1:
                top_heading_seen = True
            section.append(
                _new_paragraph(
                    text,
                    char_pr={1: HEADING_1_CHAR_PR, 2: HEADING_2_CHAR_PR, 3: HEADING_3_CHAR_PR}[level],
                    para_pr=CENTER_PARA_PR if level == 1 else BODY_PARA_PR,
                    page_break=page_break,
                )
            )
            index += 1
            continue
        if stripped.startswith("> HWPX에서는 자동 차례"):
            index += 1
            continue
        if re.match(r"^\*\*\[그림 \d+ 삽입:", stripped):
            section.append(
                _new_paragraph(
                    "[실제 화면 삽입 필요] " + _plain_text(stripped),
                    char_pr=bold_char_pr,
                    para_pr=CENTER_PARA_PR,
                )
            )
            index += 1
            continue
        text = _plain_text(stripped)
        if stripped.startswith("- "):
            text = "· " + _plain_text(stripped[2:])
        elif stripped.startswith("> "):
            text = "※ " + _plain_text(stripped[2:])
        if text:
            section.append(_new_paragraph(text))
        index += 1
    return section


def _update_content_manifest(
    content_root: ET.Element,
    images: list[EmbeddedImage],
    *,
    privacy_copy: bool,
) -> None:
    metadata = content_root.find(OPF + "metadata")
    if metadata is not None:
        title = metadata.find(OPF + "title")
        if title is not None:
            title.text = TITLE + (" 개인정보삭제 검토본" if privacy_copy else " 자동생성 검토본")
        now_utc = datetime.now(timezone.utc)
        for meta in metadata.findall(OPF + "meta"):
            name = meta.get("name")
            if name == "creator":
                meta.set("content", "전국과학전람회 출품자")
                meta.text = "전국과학전람회 출품자"
            elif name == "lastsaveby":
                meta.text = "자동 생성 검토본"
            elif name == "CreatedDate":
                meta.text = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            elif name == "ModifiedDate":
                meta.text = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            elif name == "date":
                meta.text = now_utc.strftime("%Y-%m-%d")
    manifest = content_root.find(OPF + "manifest")
    spine = content_root.find(OPF + "spine")
    if manifest is None or spine is None:
        raise ValueError("official HWPX content manifest is incomplete")
    for item in list(manifest):
        item_id = item.get("id", "")
        if item_id.startswith("section") or item_id.startswith("image"):
            manifest.remove(item)
    for item in list(spine):
        if item.get("idref", "").startswith("section"):
            spine.remove(item)
    for image in images:
        digest = base64.b64encode(hashlib.md5(image.source.read_bytes()).digest()).decode("ascii")
        ET.SubElement(
            manifest,
            OPF + "item",
            {
                "id": image.item_id,
                "href": image.archive_path,
                "media-type": image.media_type,
                "isEmbeded": "1",
                "hashkey": digest,
            },
        )
    ET.SubElement(manifest, OPF + "item", {"id": "section0", "href": "Contents/section0.xml", "media-type": "application/xml"})
    ET.SubElement(manifest, OPF + "item", {"id": "section1", "href": "Contents/section1.xml", "media-type": "application/xml"})
    ET.SubElement(spine, OPF + "itemref", {"idref": "section0", "linear": "yes"})
    ET.SubElement(spine, OPF + "itemref", {"idref": "section1", "linear": "yes"})


def _preview_image() -> bytes:
    canvas = Image.new("RGB", (640, 905), "white")
    draw = ImageDraw.Draw(canvas)
    regular_path = Path.home() / ".local/share/fonts/Pretendard/Pretendard-Regular.ttf"
    bold_path = Path.home() / ".local/share/fonts/Pretendard/Pretendard-Bold.ttf"
    fallback = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    regular_font_path = regular_path if regular_path.exists() else fallback
    bold_font_path = bold_path if bold_path.exists() else fallback
    regular = ImageFont.truetype(str(regular_font_path), 24)
    bold = ImageFont.truetype(str(bold_font_path), 34)
    small = ImageFont.truetype(str(regular_font_path), 18)
    draw.rectangle((44, 44, 596, 861), outline="#9aa7b4", width=2)
    draw.text((320, 150), "제72회 전국과학전람회", font=bold, fill="#172b4d", anchor="mm")
    draw.text((320, 310), TITLE_LINE_1, font=regular, fill="#111111", anchor="mm")
    draw.text((320, 352), TITLE_LINE_2, font=regular, fill="#111111", anchor="mm")
    draw.text((320, 680), "공식 서식 6 기반 자동 생성 검토본", font=small, fill="#555555", anchor="mm")
    draw.text((320, 718), "한글에서 열어 쪽수와 조판을 반드시 확인", font=small, fill="#b3261e", anchor="mm")
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def build_hwpx(
    template_path: Path,
    markdown_path: Path,
    output_path: Path,
    *,
    privacy_copy: bool = False,
) -> dict[str, int]:
    if not template_path.exists():
        raise FileNotFoundError(template_path)
    markdown = markdown_path.read_text(encoding="utf-8")
    images = _prepare_images(markdown, markdown_path)
    with zipfile.ZipFile(template_path) as archive:
        source_entries = {name: archive.read(name) for name in archive.namelist()}

    header_root = ET.fromstring(source_entries["Contents/header.xml"])
    header_root.set("secCnt", "2")
    bold_char_pr = _add_body_bold_style(header_root)
    template_section_root = ET.fromstring(source_entries["Contents/section1.xml"])

    cover_section = ET.Element(HS + "sec")
    cover_section.append(_make_section_properties(template_section_root, body=False))
    form_heading = copy.deepcopy(template_section_root[15])
    form_cover = copy.deepcopy(template_section_root[16])
    _fill_cover(form_cover, privacy_copy=privacy_copy)
    cover_section.extend([form_heading, form_cover])

    body_section = _markdown_to_section(
        markdown,
        markdown_path,
        template_section_root,
        images,
        bold_char_pr=bold_char_pr,
    )

    content_root = ET.fromstring(source_entries["Contents/content.hpf"])
    _update_content_manifest(content_root, images, privacy_copy=privacy_copy)

    replacements: dict[str, bytes] = {
        "Contents/header.xml": _xml_bytes(header_root),
        "Contents/section0.xml": _xml_bytes(cover_section),
        "Contents/section1.xml": _xml_bytes(body_section),
        "Contents/content.hpf": _xml_bytes(content_root),
        "Preview/PrvText.txt": (TITLE + "\n\n" + "\n".join(_plain_text(line) for line in markdown.splitlines())).encode("utf-8"),
        "Preview/PrvImage.png": _preview_image(),
    }
    omitted = {"Contents/section2.xml", "Contents/section3.xml"}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w") as archive:
        mime_info = zipfile.ZipInfo("mimetype")
        mime_info.compress_type = zipfile.ZIP_STORED
        archive.writestr(mime_info, source_entries["mimetype"])
        for name, payload in source_entries.items():
            if name == "mimetype" or name in omitted or name.startswith("Contents/section") or name in replacements:
                continue
            archive.writestr(name, payload, compress_type=zipfile.ZIP_DEFLATED)
        for name, payload in replacements.items():
            archive.writestr(name, payload, compress_type=zipfile.ZIP_DEFLATED)
        for image in images:
            archive.writestr(image.archive_path, image.source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)

    return {
        "embedded_images": len(images),
        "sections": 2,
        "tables": len(body_section.findall(f".//{HP}tbl")),
        "paragraphs": len(body_section.findall(f".//{HP}p")),
    }


def validate_hwpx(path: Path) -> dict[str, int]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if not names or names[0] != "mimetype":
            raise ValueError("HWPX mimetype must be the first package entry")
        if archive.getinfo("mimetype").compress_type != zipfile.ZIP_STORED:
            raise ValueError("HWPX mimetype must be stored without compression")
        required = {
            "mimetype",
            "version.xml",
            "Contents/header.xml",
            "Contents/section0.xml",
            "Contents/section1.xml",
            "Contents/content.hpf",
            "settings.xml",
            "META-INF/container.xml",
        }
        missing = sorted(required - set(names))
        if missing:
            raise ValueError(f"HWPX is missing required entries: {missing}")
        for name in names:
            if name.endswith(".xml") or name.endswith(".hpf"):
                ET.fromstring(archive.read(name))
        content = ET.fromstring(archive.read("Contents/content.hpf"))
        header = ET.fromstring(archive.read("Contents/header.xml"))
        if header.get("secCnt") != "2":
            raise ValueError("generated HWPX must contain cover and body sections")
        body_char = next((item for item in header.iter(HH + "charPr") if item.get("id") == BODY_CHAR_PR), None)
        body_font = body_char.find(HH + "fontRef") if body_char is not None else None
        if body_char is None or body_char.get("height") != "1100" or body_font is None or body_font.get("hangul") != "8":
            raise ValueError("body text is not linked to the official 11 pt Human Myeongjo style")
        body_para = next((item for item in header.iter(HH + "paraPr") if item.get("id") == BODY_PARA_PR), None)
        line_spacing = body_para.find(f".//{HH}lineSpacing") if body_para is not None else None
        if line_spacing is None or line_spacing.get("type") != "PERCENT" or line_spacing.get("value") != "160":
            raise ValueError("body paragraph style is not set to 160% line spacing")
        manifest = content.find(OPF + "manifest")
        hrefs = [item.get("href") for item in manifest.findall(OPF + "item")]
        unresolved = sorted(href for href in hrefs if href and href not in names)
        if unresolved:
            raise ValueError(f"manifest references missing package entries: {unresolved}")
        section = ET.fromstring(archive.read("Contents/section1.xml"))
        margin = section.find(f".//{HP}pagePr/{HP}margin")
        expected_margin = {
            "left": "5669",
            "right": "5669",
            "top": "4252",
            "bottom": "4252",
            "header": "2834",
            "footer": "2834",
        }
        if margin is None or any(margin.get(key) != value for key, value in expected_margin.items()):
            raise ValueError("body page margins do not match the official 20/15/10 mm specification")
        images = section.findall(f".//{HC}img")
        image_ids = {item.get("id") for item in manifest.findall(OPF + "item") if item.get("media-type", "").startswith("image/")}
        bad_refs = sorted({item.get("binaryItemIDRef") for item in images} - image_ids)
        if bad_refs:
            raise ValueError(f"section references unknown image ids: {bad_refs}")
        text = "".join((node.text or "") for node in section.iter(HP + "t"))
        for required_text in REQUIRED_BODY_MARKERS:
            if required_text not in text:
                raise ValueError(f"generated HWPX body is missing: {required_text}")
        placeholder_count = text.count("[실제 화면 삽입 필요]")
        if placeholder_count > 3:
            raise ValueError("generated HWPX contains an unexpected evidence-screen placeholder")
        # Keep legitimate result-table counts such as ``11/12``.  The stale
        # claim concerned the old automatic-stop replay result, not every
        # fraction with that denominator.
        if re.search(
            r"1\.643|자동\s*정지.{0,80}11/12|11/12.{0,80}자동\s*정지|11개\s*run에서\s*정지",
            text,
        ):
            raise ValueError("generated HWPX contains a stale automatic-stop replay claim")
        return {
            "entries": len(names),
            "embedded_images": len(images),
            "manifest_items": len(manifest.findall(OPF + "item")),
            "body_characters": len(text),
            "screen_placeholders": placeholder_count,
        }


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="output path; defaults to a separate normal or privacy-review file",
    )
    parser.add_argument("--privacy-copy", action="store_true", help="blank student and teacher fields on the official cover")
    args = parser.parse_args(argv)
    if args.output is None:
        args.output = DEFAULT_PRIVACY_OUTPUT if args.privacy_copy else DEFAULT_OUTPUT
    return args


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    build_summary = build_hwpx(args.template, args.markdown, args.output, privacy_copy=args.privacy_copy)
    validation_summary = validate_hwpx(args.output)
    print(f"built: {args.output}")
    print({**build_summary, **validation_summary})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
