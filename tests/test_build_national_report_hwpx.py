import re
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from tools.build_national_report_hwpx import (
    DEFAULT_MARKDOWN,
    DEFAULT_TEMPLATE,
    DEFAULT_OUTPUT,
    DEFAULT_PRIVACY_OUTPUT,
    HC,
    HP,
    OPF,
    REQUIRED_BODY_MARKERS,
    _parse_args,
    build_hwpx,
    validate_hwpx,
)


class NationalReportHwpxTests(unittest.TestCase):
    @staticmethod
    def _remove_body_marker(path, marker):
        with ZipFile(path) as archive:
            entries = [(info, archive.read(info)) for info in archive.infolist()]
        with ZipFile(path, "w") as archive:
            for info, data in entries:
                if info.filename == "Contents/section1.xml":
                    data = data.replace(marker.encode("utf-8"), b"")
                archive.writestr(info, data)

    def test_builder_embeds_official_cover_body_and_images(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.hwpx"
            result = build_hwpx(DEFAULT_TEMPLATE, DEFAULT_MARKDOWN, output)
            validation = validate_hwpx(output)

            self.assertEqual(result["sections"], 2)
            markdown = DEFAULT_MARKDOWN.read_text(encoding="utf-8")
            expected_images = len(re.findall(r"!\[[^]]*\]\([^)]+\)", markdown))
            expected_placeholders = len(re.findall(r"\*\*\[그림 \d+ 삽입:", markdown))
            self.assertEqual(result["embedded_images"], expected_images)
            self.assertEqual(validation["embedded_images"], expected_images)
            self.assertEqual(validation["screen_placeholders"], expected_placeholders)
            with ZipFile(output) as archive:
                cover = ET.fromstring(archive.read("Contents/section0.xml"))
                cover_text = "".join((node.text or "") for node in cover.iter(HP + "t"))
                body = ET.fromstring(archive.read("Contents/section1.xml"))
                content = ET.fromstring(archive.read("Contents/content.hpf"))
                manifest = content.find(OPF + "manifest")
                packaged_text = "\n".join(
                    archive.read(name).decode("utf-8", "ignore")
                    for name in archive.namelist()
                    if name.endswith((".xml", ".hpf", ".txt"))
                )

                self.assertIn("【서식 6】작품설명서 표지", cover_text)
                self.assertIn("자동 적정 보조 시스템 개발", cover_text)
                self.assertNotIn("Korea Aerospace Research Institute", packaged_text)
                self.assertNotIn("/home/jio", packaged_text)
                self.assertEqual(len(body.findall(f".//{HC}img")), expected_images)
                self.assertEqual(
                    len([item for item in manifest.findall(OPF + "item") if item.get("media-type", "").startswith("image/")]),
                    expected_images,
                )

    def test_privacy_copy_blanks_cover_identity_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "privacy.hwpx"
            build_hwpx(DEFAULT_TEMPLATE, DEFAULT_MARKDOWN, output, privacy_copy=True)
            with ZipFile(output) as archive:
                cover = ET.fromstring(archive.read("Contents/section0.xml"))
            cover_text = "".join((node.text or "") for node in cover.iter(HP + "t"))
            self.assertNotIn("[출품학생 입력]", cover_text)
            self.assertNotIn("[지도교원 입력]", cover_text)
            self.assertIn("학생부", cover_text)

    def test_cli_uses_separate_default_paths_for_normal_and_privacy_copies(self):
        self.assertEqual(_parse_args([]).output, DEFAULT_OUTPUT)
        self.assertEqual(
            _parse_args(["--privacy-copy"]).output,
            DEFAULT_PRIVACY_OUTPUT,
        )

    def test_validator_requires_current_markers_without_stale_count(self):
        required_markers = REQUIRED_BODY_MARKERS
        self.assertNotIn("144건", required_markers)
        self.assertGreaterEqual(len(required_markers), 4)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.hwpx"
            build_hwpx(DEFAULT_TEMPLATE, DEFAULT_MARKDOWN, output)
            with ZipFile(output) as archive:
                body = ET.fromstring(archive.read("Contents/section1.xml"))
            body_text = "".join((node.text or "") for node in body.iter(HP + "t"))
            self.assertNotIn("144건", body_text)
            validate_hwpx(output)

            pristine = output.read_bytes()
            for marker in required_markers:
                with self.subTest(marker=marker):
                    output.write_bytes(pristine)
                    self._remove_body_marker(output, marker)
                    with self.assertRaisesRegex(ValueError, re.escape(marker)):
                        validate_hwpx(output)


if __name__ == "__main__":
    unittest.main()
