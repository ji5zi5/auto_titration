#!/usr/bin/env python3
"""Create a poster-ready app workflow visual for the auto titration system."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/auto-titration-app-flow-mpl")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist/앱_사용흐름도_2026-08-28.png"
DASHBOARD_SCREEN = ROOT / "dist/웹GPT_보고서_최종보강자료_2026-08-06/08_보조자료/사진원본/Windows앱/Windows_전체대시보드.png"
RESULT_SCREEN = ROOT / "dist/poster_concentration_result_2026-08-28.png"
FONT_REGULAR = Path("/home/jio/.local/share/fonts/Pretendard/Pretendard-Regular.ttf")
FONT_BOLD = Path("/home/jio/.local/share/fonts/Pretendard/Pretendard-Bold.otf")

INK = "#14212B"
MUTED = "#5F6B73"
PAPER = "#F5F7F7"
CARD = "#FFFFFF"
LINE = "#D5DDE1"
BLUE = "#1F5EA8"
BLUE_SOFT = "#EAF1F8"
ORANGE = "#C86519"
ORANGE_SOFT = "#F8EEE6"
GREEN = "#197451"
GREEN_SOFT = "#E8F2ED"


def setup_fonts() -> None:
    for path in (FONT_REGULAR, FONT_BOLD):
        if path.is_file():
            font_manager.fontManager.addfont(path)
    plt.rcParams.update({"font.family": "Pretendard", "svg.fonttype": "none", "text.color": INK})


def rounded(axis, x, y, w, h, *, face=CARD, edge=LINE, width=1.4, radius=0.018, zorder=1):
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0.010,rounding_size={radius}",
        facecolor=face, edgecolor=edge, linewidth=width, zorder=zorder,
    )
    axis.add_patch(patch)
    return patch


def arrow(axis, start, end, *, color=MUTED, width=1.8, scale=20):
    axis.add_patch(FancyArrowPatch(
        start, end, arrowstyle="-|>", mutation_scale=scale,
        linewidth=width, color=color, shrinkA=0, shrinkB=0, zorder=8,
    ))


def dashboard_crop() -> np.ndarray:
    image = Image.open(DASHBOARD_SCREEN).convert("RGB")
    image = image.crop((0, 0, image.width, 500))
    return letterbox(image, (1500, 520))


def result_crop() -> np.ndarray:
    image = Image.open(RESULT_SCREEN).convert("RGB")
    return letterbox(image, (1500, 520))


def letterbox(image: Image.Image, size: tuple[int, int]) -> np.ndarray:
    canvas = Image.new("RGB", size, "white")
    contained = ImageOps.contain(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    canvas.paste(contained, ((size[0] - contained.width) // 2, (size[1] - contained.height) // 2))
    return np.asarray(canvas)


def phase_label(axis, x, y, w, text, color, fill):
    rounded(axis, x, y, w, 0.055, face=fill, edge=color, width=1.2, radius=0.014)
    axis.text(x + w / 2, y + 0.028, text, ha="center", va="center", fontsize=12.5, fontweight="bold", color=color)


def step_card(axis, x, y, w, number, title, subtitle, *, color, fill):
    rounded(axis, x, y, w, 0.235, face=CARD, edge=LINE, width=1.2, radius=0.018)
    axis.add_patch(Rectangle((x, y + 0.218), w, 0.017, facecolor=color, edgecolor=color, zorder=3))
    axis.add_patch(Circle((x + 0.024, y + 0.187), 0.017, facecolor=fill, edgecolor=color, linewidth=1.2, zorder=4))
    axis.text(x + 0.024, y + 0.187, str(number), ha="center", va="center", fontsize=9.5, fontweight="bold", color=color, zorder=5)
    axis.text(x + 0.050, y + 0.187, title, ha="left", va="center", fontsize=11.0, fontweight="bold")
    axis.text(x + w / 2, y + 0.093, subtitle, ha="center", va="center", fontsize=9.2, color=MUTED, linespacing=1.45)


def field_box(axis, x, y, w, label, value, *, color=BLUE):
    rounded(axis, x, y, w, 0.090, face=CARD, edge=LINE, width=1.0, radius=0.014)
    axis.text(x + 0.014, y + 0.064, label, ha="left", va="center", fontsize=8.8, color=MUTED, fontweight="bold")
    axis.text(x + 0.014, y + 0.029, value, ha="left", va="center", fontsize=10.5, color=INK, fontweight="bold")
    axis.add_patch(Rectangle((x, y), 0.006, 0.090, facecolor=color, edgecolor=color, zorder=4))


def build(target: Path = OUTPUT) -> None:
    """Build the compact four-stage poster version."""
    setup_fonts()
    fig, axis = plt.subplots(figsize=(12.0, 4.15), constrained_layout=True)
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")
    fig.patch.set_facecolor(PAPER)

    cards = [
        (0.035, "1", "조건 입력", "적정 종류 · 시료\n표준액 · 지시약", BLUE, BLUE_SOFT),
        (0.285, "2", "센서 수집", "색상 ROI + 열화상 ROI\nCSV 녹화 · 수동 주입", ORANGE, ORANGE_SOFT),
        (0.535, "3", "당량점 예측", "색 · 열 · 주입량\n적정 종류별 분류 모델", GREEN, GREEN_SOFT),
        (0.785, "4", "결과 확인", "농도 0.08342 M\npH 8.72 · 당량점 16.684 mL", GREEN, GREEN_SOFT),
    ]
    width = 0.180
    for index, (x, number, title, subtitle, color, fill) in enumerate(cards):
        rounded(axis, x, 0.185, width, 0.630, face=CARD, edge=color, width=1.8, radius=0.025)
        axis.add_patch(Circle((x + 0.035, 0.750), 0.025, facecolor=fill, edgecolor=color, linewidth=1.4))
        axis.text(x + 0.035, 0.750, number, ha="center", va="center", fontsize=13, fontweight="bold", color=color)
        axis.text(x + 0.070, 0.750, title, ha="left", va="center", fontsize=16, fontweight="bold", color=INK)
        axis.text(x + width / 2, 0.475, subtitle, ha="center", va="center", fontsize=12.5, color=MUTED, linespacing=1.55)
        if index < len(cards) - 1:
            arrow(axis, (x + width, 0.500), (cards[index + 1][0], 0.500), color=MUTED, width=1.8, scale=22)

    target.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(target, dpi=300, bbox_inches="tight", pad_inches=0.08, facecolor=PAPER)
    fig.savefig(target.with_suffix(".svg"), bbox_inches="tight", pad_inches=0.08, facecolor=PAPER)
    plt.close(fig)

    caption = target.with_name(target.stem + "_caption.txt")
    caption.write_text(
        "앱 사용 흐름. 장치를 연결하고 적정 조건과 두 센서 ROI를 설정한 뒤 녹화와 수동 주입을 진행한다. 색상·열화상·주입량을 공통 시각으로 기록하고 적정 종류별 분류 모델이 당량점을 추정하여 미지 시료 농도, 예측 pH와 CSV 결과를 표시한다.\n",
        encoding="utf-8",
    )

    windows_dist = Path("/mnt/c/Users/Jio/Downloads/auto_titration/dist")
    if windows_dist.is_dir():
        shutil.copy2(target, windows_dist / target.name)
        shutil.copy2(target.with_suffix(".svg"), windows_dist / target.with_suffix(".svg").name)
        shutil.copy2(caption, windows_dist / caption.name)


def main() -> int:
    build()
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
