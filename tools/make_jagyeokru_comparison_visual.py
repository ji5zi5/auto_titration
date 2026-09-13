#!/usr/bin/env python3
"""Create a poster-ready Jagyeokru vs smart titrator comparison visual."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/auto-titration-jagyeokru-mpl")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.patches import Circle, Ellipse, FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist/자격루_스마트적정기_원리비교_2026-08-28.png"
DEVICE_PHOTO = ROOT / "docs/report_assets/wet_titration_setup.jpg"
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
BRONZE = "#A8753A"
BRONZE_DARK = "#74502C"
BRONZE_LIGHT = "#D7B074"


def setup_fonts() -> None:
    for path in (FONT_REGULAR, FONT_BOLD):
        if path.is_file():
            font_manager.fontManager.addfont(path)
    plt.rcParams.update({
        "font.family": "Pretendard",
        "text.color": INK,
        "svg.fonttype": "none",
        "figure.facecolor": PAPER,
    })


def rounded_panel(axis, x, y, w, h, *, edge, face=CARD, linewidth=1.6, radius=0.025):
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0.012,rounding_size={radius}",
        facecolor=face, edgecolor=edge, linewidth=linewidth,
    )
    axis.add_patch(patch)
    return patch


def arrow(axis, start, end, *, color=MUTED, width=1.6, scale=19):
    axis.add_patch(FancyArrowPatch(
        start, end, arrowstyle="-|>", mutation_scale=scale,
        linewidth=width, color=color, shrinkA=0, shrinkB=0,
    ))


def draw_water_drop(axis, x, y, size=0.018, color=BLUE):
    points = np.array([
        [x, y + size * 1.5],
        [x - size, y],
        [x - size * 0.72, y - size * 0.75],
        [x, y - size * 1.05],
        [x + size * 0.72, y - size * 0.75],
        [x + size, y],
    ])
    axis.add_patch(Polygon(points, closed=True, facecolor=color, edgecolor="white", linewidth=0.8))


def draw_vessel(axis, cx, cy, width, height):
    axis.add_patch(Rectangle(
        (cx - width * 0.42, cy - height * 0.50),
        width * 0.84, height * 0.73,
        facecolor=BRONZE, edgecolor=BRONZE_DARK, linewidth=1.4,
    ))
    axis.add_patch(Ellipse(
        (cx, cy + height * 0.23), width, height * 0.36,
        facecolor=BRONZE_LIGHT, edgecolor=BRONZE_DARK, linewidth=1.4,
    ))
    axis.add_patch(Ellipse(
        (cx, cy + height * 0.23), width * 0.78, height * 0.19,
        facecolor="#A9D6E9", edgecolor=BLUE, linewidth=1.0,
    ))
    axis.add_patch(Rectangle(
        (cx - width * 0.06, cy - height * 0.72),
        width * 0.12, height * 0.22,
        facecolor=BRONZE_DARK, edgecolor=BRONZE_DARK,
    ))


def draw_jagyeokru(axis):
    # Three linked water vessels and a simplified float-trigger tower.
    draw_vessel(axis, 0.155, 0.650, 0.145, 0.115)
    draw_vessel(axis, 0.215, 0.510, 0.165, 0.125)
    draw_vessel(axis, 0.285, 0.365, 0.190, 0.140)
    for x, y in ((0.185, 0.575), (0.250, 0.433)):
        axis.plot([x, x + 0.025], [y, y - 0.045], color=BLUE, linewidth=2.5)
        draw_water_drop(axis, x + 0.030, y - 0.062, size=0.009)

    # Trigger tower and bell.
    axis.add_patch(FancyBboxPatch(
        (0.335, 0.335), 0.075, 0.330,
        boxstyle="round,pad=0.006,rounding_size=0.012",
        facecolor="#E7D5B8", edgecolor=BRONZE_DARK, linewidth=1.4,
    ))
    axis.plot([0.372, 0.372], [0.385, 0.590], color=BRONZE_DARK, linewidth=2.0)
    axis.add_patch(Circle((0.372, 0.425), 0.017, facecolor=BLUE_SOFT, edgecolor=BLUE, linewidth=1.2))
    axis.add_patch(Polygon(
        [[0.347, 0.625], [0.397, 0.625], [0.388, 0.675], [0.356, 0.675]],
        closed=True, facecolor=BRONZE_LIGHT, edgecolor=BRONZE_DARK, linewidth=1.3,
    ))
    axis.plot([0.372, 0.372], [0.590, 0.625], color=BRONZE_DARK, linewidth=1.6)
    arrow(axis, (0.305, 0.405), (0.352, 0.445), color=GREEN, width=1.8, scale=20)


def device_photo_array() -> np.ndarray:
    photo = Image.open(DEVICE_PHOTO).convert("RGB")
    # Keep pump, tubing, beaker and stirrer; remove most laboratory clutter.
    photo = photo.crop((0, 0, 880, 1280))
    photo = ImageOps.fit(photo, (1200, 850), method=Image.Resampling.LANCZOS, centering=(0.48, 0.52))
    return np.asarray(photo)


def step_chip(axis, x, y, w, text, *, color, fill):
    rounded_panel(axis, x, y, w, 0.085, edge=color, face=fill, linewidth=1.2, radius=0.018)
    axis.text(x + w / 2, y + 0.043, text, ha="center", va="center", fontsize=10.8, fontweight="bold")


def build(target: Path = OUTPUT) -> None:
    setup_fonts()
    fig, axis = plt.subplots(figsize=(12.0, 6.2), constrained_layout=True)
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")
    fig.patch.set_facecolor(PAPER)

    rounded_panel(axis, 0.025, 0.080, 0.445, 0.855, edge=BLUE, face=CARD, linewidth=1.8, radius=0.028)
    rounded_panel(axis, 0.530, 0.080, 0.445, 0.855, edge=GREEN, face=CARD, linewidth=1.8, radius=0.028)

    axis.text(0.060, 0.875, "자격루", fontsize=23, fontweight="bold", color=INK)
    axis.text(0.060, 0.835, "일정한 물의 흐름으로 시간을 읽다", fontsize=12.5, color=MUTED)
    axis.text(0.565, 0.875, "비접촉 스마트 적정기", fontsize=23, fontweight="bold", color=INK)
    axis.text(0.565, 0.835, "일정한 주입과 센서 변화로 당량점을 읽다", fontsize=12.5, color=MUTED)

    draw_jagyeokru(axis)

    # Device photo clipped inside a clean rounded viewport.
    photo_extent = (0.565, 0.940, 0.340, 0.785)
    photo = axis.imshow(device_photo_array(), extent=photo_extent, zorder=1, aspect="auto")
    clip = FancyBboxPatch(
        (photo_extent[0], photo_extent[2]),
        photo_extent[1] - photo_extent[0], photo_extent[3] - photo_extent[2],
        boxstyle="round,pad=0.002,rounding_size=0.022",
        transform=axis.transData,
    )
    photo.set_clip_path(clip)
    axis.add_patch(FancyBboxPatch(
        (photo_extent[0], photo_extent[2]),
        photo_extent[1] - photo_extent[0], photo_extent[3] - photo_extent[2],
        boxstyle="round,pad=0.002,rounding_size=0.022",
        facecolor="none", edgecolor=GREEN, linewidth=1.4, zorder=3,
    ))

    # Sensor badges on the device image.
    rounded_panel(axis, 0.585, 0.705, 0.115, 0.052, edge=BLUE, face=BLUE_SOFT, linewidth=1.1, radius=0.012)
    axis.text(0.642, 0.731, "색상 카메라", ha="center", va="center", fontsize=9.8, fontweight="bold", color=BLUE)
    rounded_panel(axis, 0.805, 0.705, 0.115, 0.052, edge=ORANGE, face=ORANGE_SOFT, linewidth=1.1, radius=0.012)
    axis.text(0.862, 0.731, "열화상 카메라", ha="center", va="center", fontsize=9.8, fontweight="bold", color=ORANGE)

    # Four-stage comparisons.
    left_steps = ["물의 일정한 흐름", "누적 물의 양", "경과 시간", "시각 알림"]
    right_steps = ["빠른 연속 주입", "누적 주입량", "접근 신호 감지", "미세 주입·정지"]
    x_left = [0.050, 0.150, 0.250, 0.350]
    x_right = [0.555, 0.655, 0.755, 0.855]
    for i, (x, text) in enumerate(zip(x_left, left_steps)):
        step_chip(axis, x, 0.180, 0.090, text, color=BLUE, fill=BLUE_SOFT)
        if i < 3:
            arrow(axis, (x + 0.090, 0.222), (x_left[i + 1], 0.222), color=MUTED, width=1.2, scale=14)
    for i, (x, text) in enumerate(zip(x_right, right_steps)):
        color = ORANGE if i == 2 else GREEN
        fill = ORANGE_SOFT if i == 2 else GREEN_SOFT
        step_chip(axis, x, 0.180, 0.090, text, color=color, fill=fill)
        if i < 3:
            arrow(axis, (x + 0.090, 0.222), (x_right[i + 1], 0.222), color=MUTED, width=1.2, scale=14)

    # Shared principle band.
    rounded_panel(axis, 0.205, 0.020, 0.590, 0.082, edge=INK, face=INK, linewidth=0, radius=0.020)
    axis.text(0.500, 0.061, "공통 원리  ·  일정한 흐름을 액체량으로 환산하여 상태를 판단", ha="center", va="center", fontsize=14.5, fontweight="bold", color="white")

    target.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(target, dpi=300, bbox_inches="tight", pad_inches=0.08, facecolor=PAPER)
    fig.savefig(target.with_suffix(".svg"), bbox_inches="tight", pad_inches=0.08, facecolor=PAPER)
    plt.close(fig)

    caption = target.with_name(target.stem + "_caption.txt")
    caption.write_text(
        "자격루와 비접촉 스마트 적정기의 원리 비교. 자격루는 일정한 물의 흐름과 누적량을 시간 및 시각 알림으로 연결한다. 본 장치는 적정액을 연속 주입하다가 색상·열화상 변화로 종말점 접근을 감지하면 미세 주입과 안정화·재판정을 반복한 뒤 정지하도록 구성하였다.\n",
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
