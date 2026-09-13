#!/usr/bin/env python3
"""Validate poster HTML visuals against evidence, layout, and delivery gates."""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image, ImageStat


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "poster_html_visuals_2026-08-28"
WINDOWS_OUT = Path("/mnt/c/Users/Jio/Downloads/auto_titration/dist/poster_html_visuals_2026-08-28")


EXPECTED = {
    "01_계산값_관찰값_추정값": ["계산값", "관찰값", "추정값", "직접 측정 피드백과 구분", "열화상은 보조 관찰값"],
    "02_개발결과_검증범위": ["4 × 3", "2,030,370", "0.30%", "독립 검증 정확도", "CV 0.96%", "정확도 평가는 불가"],
    "03_센서입력군_기여도": ["1.55%", "3.66%", "1.52%", "개선 조건 존재", "악화 조건 존재", "95% 구간에 0 포함", "열화상 0값 구간"],
    "04_미세주입_자동정지_안전": ["접근 점수 0.20", "0.50초", "STEP 5", "점수 0.30", "색 변화 0.4초", "제어 안전 제한", "실패-폐쇄", "실측 방울 부피"],
    "05_5스텝_습식검증계획": ["초기 10%", "중간 50%", "말기 90%", "STEP 5", "각 최소 10회", "V = Δm / ρ(T)", "아직 미측정"],
    "06_25fps_기록파이프라인": ["공통 PC 시각", "기록 전용 FIFO", "3.66 ms", "25 fps", "입력 순서 보존", "누락 없음"],
    "07_전체시스템_구성도": ["Arduino · A4988", "스테퍼 모터 · T8", "100 mL 시린지", "HIKMICRO Mini2", "Windows 수집기", "당량점 부피 · 미지 농도"],
    "08_머신러닝_분석흐름": ["색상 특징", "열화상 특징", "현재 주입량", "실험별 외부 제외 검증", "PLS 회귀", "RBF 커널 릿지", "선형 판별분석", "이차 판별분석", "독립 검증값 아님"],
}


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.suppressed_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"style", "script"}:
            self.suppressed_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script"} and self.suppressed_depth:
            self.suppressed_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.suppressed_depth and data.strip():
            self.parts.append(data.strip())


def visible_text(html: str) -> str:
    parser = TextExtractor()
    parser.feed(html)
    return re.sub(r"\s+", " ", " ".join(parser.parts))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    errors: list[str] = []
    checks: list[dict[str, object]] = []
    png_hashes: dict[str, str] = {}

    for stem, phrases in EXPECTED.items():
        html_path = OUT / f"{stem}.html"
        png_path = OUT / f"{stem}.png"
        if not html_path.exists():
            errors.append(f"missing HTML: {stem}")
            continue
        if not png_path.exists():
            errors.append(f"missing PNG: {stem}")
            continue

        html = html_path.read_text(encoding="utf-8")
        text = visible_text(html)
        missing = [phrase for phrase in phrases if phrase not in text]
        if missing:
            errors.append(f"{stem}: missing required text {missing}")
        for token in ("Pretendard", "border-radius:30px", "#f8fafc", "class=\"canvas\""):
            if token not in html:
                errors.append(f"{stem}: shared design token missing: {token}")
        if re.search(r"\d[\d,]*\s*행\b", text):
            errors.append(f"{stem}: row-count language remains in visible poster text")
        if any(forbidden in text for forbidden in ("12회", "1,822행", "120행", "11행")):
            errors.append(f"{stem}: forbidden dataset-count phrase remains")
        numeric_trials = re.findall(r"\d[\d,]*\s*회\b", text)
        allowed_trials = ["10회"] if stem == "05_5스텝_습식검증계획" else []
        unexpected_trials = [trial for trial in numeric_trials if trial.replace(" ", "") not in allowed_trials]
        if unexpected_trials:
            errors.append(f"{stem}: numeric experiment-count language remains: {unexpected_trials}")
        if re.search(r"\b\d+\s*runs?\b", text, flags=re.IGNORECASE):
            errors.append(f"{stem}: numeric run-count language remains")
        compact_html = re.sub(r"\s+", "", html).lower()
        hidden_attribute = bool(re.search(r"<[^>]+\shidden(?:=|\s|>)", html, flags=re.IGNORECASE))
        offscreen_css = bool(re.search(r"(?:left|top|right|bottom):-\d{3,}(?:px|rem|vw|vh)", compact_html))
        transparent_css = bool(re.search(r"opacity:0(?:[;}])", compact_html))
        if (
            any(hidden in compact_html for hidden in ("display:none", "visibility:hidden"))
            or hidden_attribute
            or offscreen_css
            or transparent_css
        ):
            errors.append(f"{stem}: hidden-content styling detected")

        image = Image.open(png_path).convert("RGB")
        if image.size != (3200, 1520):
            errors.append(f"{stem}: PNG size {image.size}, expected (3200, 1520)")
        dpi = Image.open(png_path).info.get("dpi", (0, 0))
        if min(dpi) < 299:
            errors.append(f"{stem}: PNG dpi {dpi}, expected 300")
        stat = ImageStat.Stat(image.resize((160, 76)))
        if max(stat.stddev) < 8:
            errors.append(f"{stem}: screenshot appears nearly blank")

        windows_html = WINDOWS_OUT / html_path.name
        windows_png = WINDOWS_OUT / png_path.name
        if not windows_html.exists() or not windows_png.exists():
            errors.append(f"{stem}: Windows copy missing")
        elif sha256(png_path) != sha256(windows_png):
            errors.append(f"{stem}: Windows PNG hash mismatch")

        image_hash = sha256(png_path)
        png_hashes[stem] = image_hash
        checks.append(
            {
                "name": stem,
                "required_phrases": len(phrases),
                "missing_phrases": missing,
                "png_size": image.size,
                "dpi": dpi,
                "sha256": image_hash,
            }
        )

    global_rules = {
        "visual_count": len(checks),
        "expected_count": len(EXPECTED),
        "no_fake_wet_measurement": "아직 미측정" in visible_text((OUT / "05_5스텝_습식검증계획.html").read_text(encoding="utf-8")),
        "ml_result_qualified": "독립 검증값 아님" in visible_text((OUT / "08_머신러닝_분석흐름.html").read_text(encoding="utf-8")),
        "nominal_pulse_qualified": "실측 방울 부피" in visible_text((OUT / "04_미세주입_자동정지_안전.html").read_text(encoding="utf-8")),
    }
    if len(checks) != len(EXPECTED):
        errors.append(f"validated {len(checks)} visuals, expected {len(EXPECTED)}")
    if len(set(png_hashes.values())) != len(png_hashes):
        errors.append("cross-visual uniqueness failed: duplicate PNG hashes detected")
    if not all(global_rules.values()):
        errors.append(f"global evidence rule failed: {global_rules}")

    evidence_pairs = [
        ("02_개발결과_검증범위", "0.30%", "독립 검증 정확도"),
        ("03_센서입력군_기여도", "1.52%", "일관된 향상은 확인되지 않음"),
        ("04_미세주입_자동정지_안전", "0.0495 mL", "명목 부피"),
        ("05_5스텝_습식검증계획", "0.0495 mL", "실측 참값이 아닌 명목 기준"),
    ]
    for stem, claim, qualifier in evidence_pairs:
        text = visible_text((OUT / f"{stem}.html").read_text(encoding="utf-8"))
        if claim in text and qualifier not in text:
            errors.append(f"{stem}: claim {claim!r} lacks qualifier {qualifier!r}")

    report = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "global_rules": global_rules,
        "checks": checks,
    }
    (OUT / "validation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
