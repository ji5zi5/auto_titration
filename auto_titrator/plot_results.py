"""Generate lightweight SVG plots for evaluation metrics."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Mapping


def _metric(metrics: Mapping[str, Any], name: str) -> float:
    value = metrics.get(name)
    if value is None or value == "":
        return 0.0
    return float(value)


def plot_error_comparison_svg(metrics: Mapping[str, Any], output_path: str | Path) -> Path:
    """Create a simple bar chart comparing color endpoint vs ML error."""

    bars = [
        ("Color endpoint", _metric(metrics, "mean_abs_color_endpoint_error_ml"), "#d97706"),
        ("ML prediction", _metric(metrics, "mean_abs_ml_prediction_error_ml"), "#2563eb"),
    ]
    max_value = max([value for _, value, _ in bars] + [1.0])
    width = 640
    height = 320
    left = 180
    bar_height = 52
    gap = 38
    top = 90
    plot_width = 380

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="24" y="40" font-family="Arial, sans-serif" font-size="22" font-weight="700">'
        "Endpoint vs ML absolute error</text>",
        '<text x="24" y="66" font-family="Arial, sans-serif" font-size="13" fill="#555">'
        "Lower mL error is better. Thermal/color data do not directly stop the pump.</text>",
    ]
    for index, (label, value, color) in enumerate(bars):
        y = top + index * (bar_height + gap)
        bar_width = 0 if max_value == 0 else int((value / max_value) * plot_width)
        safe_label = html.escape(label)
        lines.extend(
            [
                f'<text x="24" y="{y + 33}" font-family="Arial, sans-serif" font-size="15">{safe_label}</text>',
                f'<rect x="{left}" y="{y}" width="{bar_width}" height="{bar_height}" rx="8" fill="{color}"/>',
                f'<text x="{left + bar_width + 10}" y="{y + 33}" font-family="Arial, sans-serif" font-size="15">'
                f"{value:.3f} mL</text>",
            ]
        )
    lines.append("</svg>")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an SVG bar chart from evaluation metrics JSON.")
    parser.add_argument("--metrics", required=True, help="Metrics JSON from auto_titrator.evaluation")
    parser.add_argument("--output", default="data/labeled/error-comparison.svg", help="Output SVG path")
    args = parser.parse_args()

    metrics = json.loads(Path(args.metrics).read_text(encoding="utf-8"))
    output = plot_error_comparison_svg(metrics, args.output)
    print(f"saved plot: {output}")


if __name__ == "__main__":
    main()
