"""USB visible + thermal-palette data collection app."""

from __future__ import annotations

import argparse
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np
import yaml

from .camera import CameraConfig, UsbCamera
from .color_analysis import ColorFeatureExtractor, Roi, prefix_features
from .collection import build_collection_row
from .config import load_config
from .data_logger import CsvDataLogger
from .experiment_config import ExperimentConfig
from .thermal_camera import ThermalPaletteAnalyzer


CameraFactory = Callable[[dict[str, Any], str, str], Any]


def _roi_from_config(config: dict[str, Any], section: str) -> Roi | None:
    roi = config[section].get("roi", "auto")
    if roi in (None, "auto"):
        return None
    return Roi(x=int(roi["x"]), y=int(roi["y"]), width=int(roi["width"]), height=int(roi["height"]))


def _resolve_roi(roi: Roi | None, frame_rgb: np.ndarray) -> Roi:
    """Return configured ROI, or a centered auto ROI sized to half the frame."""

    if roi is not None:
        return roi
    frame_h, frame_w = frame_rgb.shape[:2]
    width = max(1, frame_w // 2)
    height = max(1, frame_h // 2)
    return Roi(
        x=(frame_w - width) // 2,
        y=(frame_h - height) // 2,
        width=width,
        height=height,
    )


def _camera_from_config(config: dict[str, Any], section: str, name: str) -> UsbCamera:
    item = config[section]
    return UsbCamera(
        CameraConfig(
            device_index=int(item.get("device_index", 0)),
            width=item.get("width"),
            height=item.get("height"),
            backend=item.get("backend"),
            name=name,
        )
    )


def _experiment_from_config(config: dict[str, Any]) -> ExperimentConfig:
    if "experiment" not in config:
        raise ValueError("config must include an experiment section")
    return ExperimentConfig.from_mapping(config["experiment"])


def _pump_state_for_row(
    *,
    pump_state_provider: Any | None,
    elapsed_s: float,
    estimated_ml_per_second: float,
) -> dict[str, Any]:
    if pump_state_provider is None:
        return {
            "pump_mode": "estimated",
            "pump_state": "not_connected",
            "injected_volume_ml": round(elapsed_s * estimated_ml_per_second, 4),
            "pump_run_rate_ml_per_s": estimated_ml_per_second,
        }
    snapshot = dict(pump_state_provider.snapshot())
    running_rate = float(snapshot.get("pump_run_rate_ml_per_s") or 0.0)
    if snapshot.get("pump_state") == "running" and running_rate > 0:
        step_volume = float(snapshot.get("injected_volume_ml") or 0.0)
        snapshot["injected_volume_ml"] = round(step_volume + elapsed_s * running_rate, 4)
    return snapshot


def run_collection(
    config_path: str | Path,
    *,
    camera_factory: CameraFactory = _camera_from_config,
    pump_state_provider: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    config = load_config(config_path)
    experiment = _experiment_from_config(config)
    output_dir = Path(config.get("output", {}).get("directory", "data/raw"))
    output_name = config.get("output", {}).get("filename") or f"run-{datetime.now():%Y%m%d-%H%M%S}.csv"
    output_path = output_dir / output_name

    visible_camera = None
    thermal_camera = None
    thermal_enabled = bool(config.get("thermal_camera", {}).get("enabled", True))
    visible_roi = _roi_from_config(config, "visible_camera")
    thermal_roi = _roi_from_config(config, "thermal_camera") if thermal_enabled else None
    pump_config = config.get("pump", {})
    estimated_ml_per_second = float(pump_config.get("estimated_ml_per_second", 0.0))
    max_frames = config.get("collection", {}).get("max_frames")
    max_frames = int(max_frames) if max_frames else None
    sample_interval_s = float(config.get("collection", {}).get("sample_interval_s", 0.2))

    visible_analyzer = ColorFeatureExtractor()
    thermal_analyzer = ThermalPaletteAnalyzer()
    previous_visible: dict[str, float] | None = None
    previous_thermal: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = []

    start = time.monotonic()
    frame_id = 0
    try:
        visible_camera = camera_factory(config, "visible_camera", "visible camera")
        if thermal_enabled:
            thermal_camera = camera_factory(config, "thermal_camera", "Mini2 V2 USB thermal camera")
        with CsvDataLogger(output_path) as logger:
            while max_frames is None or frame_id < max_frames:
                now = time.monotonic() - start
                visible_frame = visible_camera.read_rgb()
                base_visible = visible_analyzer.extract(
                    visible_frame,
                    _resolve_roi(visible_roi, visible_frame),
                    previous_visible,
                )
                visible_features = prefix_features(base_visible, "visible")
                previous_visible = base_visible

                thermal_features: dict[str, Any] | None = None
                if thermal_camera is not None:
                    thermal_frame = thermal_camera.read_rgb()
                    thermal_features = thermal_analyzer.extract(
                        thermal_frame,
                        _resolve_roi(thermal_roi, thermal_frame),
                        previous_thermal,
                    )
                    previous_thermal = thermal_features

                pump_state = _pump_state_for_row(
                    pump_state_provider=pump_state_provider,
                    elapsed_s=now,
                    estimated_ml_per_second=estimated_ml_per_second,
                )
                row = build_collection_row(
                    experiment=experiment,
                    time_s=round(now, 3),
                    frame_id=frame_id,
                    injected_volume_ml=float(pump_state["injected_volume_ml"]),
                    visible_features=visible_features,
                    thermal_features=thermal_features,
                    pump_state=pump_state,
                    history_rows=rows,
                )
                rows.append(row)
                logger.write_row(row)
                frame_id += 1
                sleep(sample_interval_s)
    except KeyboardInterrupt:
        pass
    finally:
        if visible_camera is not None:
            visible_camera.release()
        if thermal_camera is not None:
            thermal_camera.release()
    return output_path


class _StaticRgbCamera:
    def __init__(self, frame_rgb: np.ndarray) -> None:
        self._frame_rgb = frame_rgb

    def read_rgb(self) -> np.ndarray:
        return self._frame_rgb

    def release(self) -> None:
        pass


def run_dry_run_smoke(output_path: str | Path | None = None) -> Path:
    """Run one hardware-free collection frame using synthetic cameras and no pump commands."""

    output = Path(output_path) if output_path is not None else Path("data/raw/dry-run-smoke.csv")
    output.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "experiment": {
            "experiment_id": "smoke-test",
            "titration_type": "strong_acid_strong_base",
            "sample_name": "HCl",
            "sample_concentration_M": 0.1,
            "sample_volume_ml": 10.0,
            "sample_valence": 1,
            "titrant_name": "NaOH",
            "titrant_concentration_M": 0.1,
            "titrant_valence": 1,
            "indicator": "phenolphthalein",
        },
        "visible_camera": {
            "device_index": 0,
            "roi": {"x": 0, "y": 0, "width": 2, "height": 2},
        },
        "thermal_camera": {
            "enabled": True,
            "device_index": 1,
            "roi": {"x": 0, "y": 0, "width": 2, "height": 2},
        },
        "collection": {"sample_interval_s": 0, "max_frames": 1},
        "output": {"directory": str(output.parent), "filename": output.name},
    }
    visible_frame = np.full((2, 2, 3), [120, 80, 40], dtype=np.uint8)
    thermal_frame = np.full((2, 2, 3), [20, 80, 120], dtype=np.uint8)
    cameras = {
        "visible_camera": _StaticRgbCamera(visible_frame),
        "thermal_camera": _StaticRgbCamera(thermal_frame),
    }

    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "dry-run-smoke.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        return run_collection(
            config_path,
            camera_factory=lambda _config, section, _name: cameras[section],
            sleep=lambda _seconds: None,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect visible camera and Mini2 V2 USB thermal-palette CSV data.")
    parser.add_argument("--config", default="auto_titrator/config.yaml", help="Path to YAML configuration file")
    parser.add_argument("--dry-run-smoke", action="store_true", help="Run one synthetic-camera dry-run smoke check")
    parser.add_argument("--smoke-output", default="data/raw/dry-run-smoke.csv", help="Dry-run smoke CSV output path")
    parser.add_argument("--analyze-simulated", action="store_true", help="Run status-only simulated equivalence analysis")
    parser.add_argument("--analysis-output", default="data/raw/simulated-equivalence-result.json", help="Simulated analysis JSON output path")
    args = parser.parse_args()
    if args.analyze_simulated:
        from .live_app import run_simulated_equivalence_analysis

        result = run_simulated_equivalence_analysis(args.analysis_output)
        print(
            f"saved analysis JSON: {args.analysis_output} "
            f"({result.estimated_equivalence_volume_ml:g} mL at {result.estimated_equivalence_time_s:g} s)"
        )
    elif args.dry_run_smoke:
        output_path = run_dry_run_smoke(args.smoke_output)
        print(f"saved CSV: {output_path}")
    else:
        output_path = run_collection(args.config)
        print(f"saved CSV: {output_path}")


if __name__ == "__main__":
    main()
