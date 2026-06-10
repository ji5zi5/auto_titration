"""Simple launcher for the auto titration project.

Use this file from the repository root:

    python3 run.py
    python3 run.py cameras
    python3 run.py visible
    python3 run.py dual
    python3 run.py collect
    python3 run.py analyze-simulated
"""

from __future__ import annotations

import argparse
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from auto_titrator.main import run_collection, run_dry_run_smoke


def quick_config(
    *,
    visible_index: int = 0,
    thermal_index: int | None = None,
    visible_backend: str | None = None,
    thermal_backend: str | None = None,
    frames: int = 30,
    interval_s: float = 0.1,
    output_name: str | None = None,
) -> dict[str, Any]:
    """Build a safe no-pump config for quick camera CSV tests."""

    output = output_name or f"quick-{datetime.now():%Y%m%d-%H%M%S}.csv"
    return {
        "experiment": {
            "experiment_id": "quick-test",
            "titration_type": "strong_acid_strong_base",
            "sample_name": "water-test",
            "sample_concentration_M": 0.1,
            "sample_volume_ml": 10.0,
            "sample_valence": 1,
            "titrant_name": "water-test",
            "titrant_concentration_M": 0.1,
            "titrant_valence": 1,
            "indicator": "none",
        },
        "visible_camera": {
            "device_index": visible_index,
            "backend": visible_backend,
            "roi": "auto",
        },
        "thermal_camera": {
            "enabled": thermal_index is not None,
            "device_index": thermal_index or 1,
            "backend": thermal_backend,
            "roi": "auto",
        },
        "pump": {
            "enabled": False,
            "estimated_ml_per_second": 0.0,
        },
        "collection": {
            "sample_interval_s": interval_s,
            "max_frames": frames,
        },
        "output": {
            "directory": "data/raw",
            "filename": output,
        },
    }


def run_quick_collection(config: dict[str, Any]) -> Path:
    """Run collection from an in-memory config by writing a temporary YAML file."""

    Path("data/raw").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "quick-config.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        return run_collection(config_path)


def run_ph_curve_export(
    *,
    config_path: str | Path,
    output_path: str | Path,
    step_volume_ml: float = 0.1,
    max_titrant_volume_ml: float | None = None,
) -> Path:
    """Export a theoretical pH curve from the experiment section of a config."""

    from auto_titrator.chemistry import generate_theoretical_ph_curve, write_theoretical_ph_curve_csv
    from auto_titrator.experiment_config import ExperimentConfig

    with Path(config_path).open(encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    experiment_values = dict(config["experiment"])
    experiment = ExperimentConfig.from_mapping(experiment_values)
    curve = generate_theoretical_ph_curve(
        sample_concentration_m=experiment.sample_concentration_m,
        sample_volume_ml=experiment.sample_volume_ml,
        sample_valence=experiment.sample_valence,
        titrant_concentration_m=experiment.titrant_concentration_m,
        titrant_valence=experiment.titrant_valence,
        titration_type=experiment.titration_type,
        sample_pka=_sample_pka_from_config(experiment_values),
        titrant_pkb=_titrant_pkb_from_config(experiment_values),
        step_volume_ml=step_volume_ml,
        max_titrant_volume_ml=max_titrant_volume_ml,
    )
    return write_theoretical_ph_curve_csv(curve, output_path)


def _sample_pka_from_config(values: dict[str, Any]) -> float | None:
    value = values.get("selected_pka_value")
    if value not in (None, ""):
        return float(value)
    ka = values.get("ka", values.get("Ka"))
    if ka in (None, ""):
        return None
    import math

    return -math.log10(float(ka))


def _titrant_pkb_from_config(values: dict[str, Any]) -> float | None:
    value = values.get("selected_pkb_value")
    if value not in (None, ""):
        return float(value)
    kb = values.get("kb", values.get("Kb"))
    if kb in (None, ""):
        return None
    import math

    return -math.log10(float(kb))


def scan_cameras(max_index: int = 6) -> int:
    """Print OpenCV camera indices that can be opened."""

    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError:
        print("opencv-python이 설치 안 됨. 먼저: pip install -r requirements.txt")
        return 1

    found: list[int] = []
    for index in range(max_index):
        cap = cv2.VideoCapture(index)
        ok = cap.isOpened()
        if ok:
            found.append(index)
        print(f"{index}: {'OK' if ok else 'no'}")
        cap.release()

    if found:
        print(f"\n사용 가능 카메라: {found}")
        print(f"예: python3 run.py visible --camera {found[0]}")
    else:
        print("\n카메라가 안 잡힘. USB/권한/다른 앱 사용 여부 확인.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple auto-titration launcher")
    sub = parser.add_subparsers(dest="command")

    smoke = sub.add_parser("smoke", help="No-hardware synthetic CSV test")
    smoke.add_argument("--output", default="data/raw/smoke.csv")

    cameras = sub.add_parser("cameras", help="List OpenCV camera indices")
    cameras.add_argument("--max", type=int, default=6)

    visible = sub.add_parser("visible", help="Visible-camera-only CSV test; pump off")
    visible.add_argument("--camera", type=int, default=0)
    visible.add_argument("--backend", default=None, help="OpenCV backend: any, msmf, or dshow")
    visible.add_argument("--frames", type=int, default=30)
    visible.add_argument("--interval", type=float, default=0.1)

    dual = sub.add_parser("dual", help="Visible + Mini2/thermal-palette CSV test; pump off")
    dual.add_argument("--visible", type=int, default=0)
    dual.add_argument("--thermal", type=int, default=1)
    dual.add_argument("--visible-backend", default=None, help="OpenCV backend for visible camera")
    dual.add_argument("--thermal-backend", default="msmf", help="OpenCV backend for Mini2; your probe showed msmf works")
    dual.add_argument("--frames", type=int, default=30)
    dual.add_argument("--interval", type=float, default=0.1)

    collect = sub.add_parser("collect", help="Run full auto_titrator/config.yaml")
    collect.add_argument("--config", default="auto_titrator/config.yaml")

    simulated = sub.add_parser("analyze-simulated", help="Run status-only simulated equivalence analysis")
    simulated.add_argument("--output", default="data/raw/simulated-equivalence-result.json")

    ph_curve = sub.add_parser("ph-curve", help="Export theoretical titration pH curve CSV from config")
    ph_curve.add_argument("--config", default="auto_titrator/config.yaml")
    ph_curve.add_argument("--output", default="data/raw/theoretical-ph-curve.csv")
    ph_curve.add_argument("--step-ml", type=float, default=0.1)
    ph_curve.add_argument("--max-ml", type=float, default=None)

    sub.add_parser("test", help="Run unittest checks")
    return parser


def main_with_args(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "smoke"

    if command == "smoke":
        output = run_dry_run_smoke(getattr(args, "output", "data/raw/smoke.csv"))
        print(f"OK: smoke CSV 저장됨 -> {output}")
        print("다음: python3 run.py cameras")
        return 0

    if command == "cameras":
        return scan_cameras(args.max)

    if command == "visible":
        output = run_quick_collection(
            quick_config(
                visible_index=args.camera,
                visible_backend=args.backend,
                frames=args.frames,
                interval_s=args.interval,
            )
        )
        print(f"OK: visible CSV 저장됨 -> {output}")
        return 0

    if command == "dual":
        output = run_quick_collection(
            quick_config(
                visible_index=args.visible,
                thermal_index=args.thermal,
                visible_backend=args.visible_backend,
                thermal_backend=args.thermal_backend,
                frames=args.frames,
                interval_s=args.interval,
            )
        )
        print(f"OK: visible+thermal CSV 저장됨 -> {output}")
        return 0

    if command == "collect":
        output = run_collection(args.config)
        print(f"OK: full collection CSV 저장됨 -> {output}")
        return 0

    if command == "analyze-simulated":
        from auto_titrator.live_app import run_simulated_equivalence_analysis

        result = run_simulated_equivalence_analysis(args.output)
        print(
            "OK: simulated status-only analysis 저장됨 -> "
            f"{args.output} ({result.estimated_equivalence_volume_ml:g} mL, "
            f"{result.estimated_equivalence_time_s:g} s)"
        )
        return 0

    if command == "ph-curve":
        output = run_ph_curve_export(
            config_path=args.config,
            output_path=args.output,
            step_volume_ml=args.step_ml,
            max_titrant_volume_ml=args.max_ml,
        )
        print(f"OK: theoretical pH curve CSV 저장됨 -> {output}")
        return 0

    if command == "test":
        import subprocess
        import sys

        return subprocess.call([sys.executable, "-m", "unittest", "discover", "-v"])

    parser.print_help()
    return 2


def main() -> int:
    return main_with_args()


if __name__ == "__main__":
    raise SystemExit(main())
