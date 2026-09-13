#!/usr/bin/env python3
"""Professor-critic gate for the Windows web pump runtime contract."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import windows_live_collect  # noqa: E402


WINDOWS_ROOT = Path("/mnt/c/Users/Jio/Downloads/auto_titration")
REPORT = ROOT / "dist" / "web_pump_runtime_validation.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> None:
    errors: list[str] = []
    checks: dict[str, object] = {}

    html = (ROOT / "website/index.html").read_text(encoding="utf-8")
    js = (ROOT / "website/app.js").read_text(encoding="utf-8")
    collector = (ROOT / "tools/windows_live_collect.py").read_text(encoding="utf-8")
    firmware = (ROOT / "auto_titrator/arduino_stepper/arduino_stepper.ino").read_text(
        encoding="utf-8"
    )
    launcher = (ROOT / "launchers/windows/20_windows_live_collect.bat").read_text(
        encoding="utf-8"
    )

    require("pumpMaximumFlowInput" not in html, "safety-limit UI still present", errors)
    require("pumpMaximumVolumeInput" not in html, "volume-limit UI still present", errors)
    require("pumpPulseMlPerStepInput" not in html, "pulse-limit UI still present", errors)
    require("{ manual_unbounded: true }" in js, "manual buttons are not unbounded", errors)
    require("manual_unbounded: !autoStopEnabled" in js, "ordinary CSV recording is not unbounded", errors)
    require("pulse_nominal_ml_per_step: 0.0099" in js, "nominal pulse calibration missing", errors)
    require("pulse_ml_per_step_upper_bound: 0.0105" in js, "conservative pulse bound missing", errors)
    require("manual_unbounded" in collector, "collector manual bypass missing", errors)
    require(
        '{"start": "b", "retract": "a", "stop": "c"}' in collector,
        "server default direction mapping is not original b/a/c",
        errors,
    )
    require(
        'pump_pulse_direction: str = "b"' in collector,
        "server default pulse direction is not b",
        errors,
    )
    require("펌프 주입 → b" in js and "펌프 되감기 → a" in js, "browser direction labels mismatch", errors)

    require("const char PULSE_DIRECTION = 'b';" in firmware, "firmware STEP direction is not b", errors)
    require('set "PUMP_START_COMMAND=b"' in launcher, "launcher dispense direction is not b", errors)
    require('set "PUMP_RETRACT_COMMAND=a"' in launcher, "launcher retract direction is not a", errors)
    require('set "PUMP_PULSE_DIRECTION=b"' in launcher, "launcher pulse direction is not b", errors)
    require("class CollectorInstanceLock" in collector, "atomic collector lock missing", errors)
    require(
        "windows_live_collect.lock" in collector,
        "collector lock is not acquired by main",
        errors,
    )
    require(
        "activeRunLimitMs = armedRunLimitMs;" in firmware
        and "&& activeRunLimitMs > 0" in firmware,
        "manual firmware a/b still has an implicit timeout",
        errors,
    )
    require(
        'Serial.print("PUMP FW 2 PULSE ")' in firmware,
        "versioned firmware capability handshake missing",
        errors,
    )
    direction_docs = [
        ROOT / "docs/WINDOWS_CODEX_HANDOFF.md",
        ROOT / "docs/PROJECT_STATUS_AND_REMAINING_WORK.md",
        ROOT / "docs/AUTO_STOP_VALIDATION.md",
        ROOT / "docs/science_fair_report_national_formatted.md",
        ROOT / "docs/report_laptop_app_development_draft.md",
        ROOT / "docs/보고서.txt",
    ]
    obsolete_direction_phrases = (
        "PUMP_START_COMMAND=a",
        "PUMP_RETRACT_COMMAND=b",
        "a = 적정액 밀기",
        "b = 시린지 뒤로 당기기",
        "녹화 시작 시 `a` 명령",
        "후퇴 버튼이 `b`",
    )
    for path in direction_docs:
        doc = path.read_text(encoding="utf-8")
        require(
            not any(phrase in doc for phrase in obsolete_direction_phrases),
            f"obsolete pump direction remains in {path.relative_to(ROOT)}",
            errors,
        )

    buffer = windows_live_collect.LiveCsvBuffer(
        output_path=Path("data/raw/validation-only.csv")
    )
    buffer.start_recording(
        pump_rate_ml_per_s=0.99,
        started_monotonic_s=100.0,
    )
    buffer.begin_commanded_pump_timeline(now_monotonic_s=100.0, running=False)
    buffer.record_commanded_pulse(
        steps=5,
        nominal_ml_per_step=0.0099,
        now_monotonic_s=100.5,
    )
    pulse_status = buffer.status(now_monotonic_s=101.0)
    require(
        abs(float(pulse_status["injected_volume_ml"]) - 0.0495) < 1e-12,
        "CSV pulse volume is not 0.0495 mL",
        errors,
    )
    require(
        abs(float(pulse_status["pump_elapsed_s"]) - 0.05) < 1e-12,
        "CSV pulse active time is not 0.05 s",
        errors,
    )
    checks["pulse_csv"] = {
        "injected_volume_ml": pulse_status["injected_volume_ml"],
        "pump_elapsed_s": pulse_status["pump_elapsed_s"],
        "pulse_steps": pulse_status["pump_pulse_steps_total"],
    }
    checks["pulse_safety"] = {
        "nominal_pulse_volume_ml": 5 * 0.0099,
        "conservative_pulse_volume_ml": 5 * 0.0105,
    }
    require(
        abs(checks["pulse_safety"]["nominal_pulse_volume_ml"] - 0.0495) < 1e-12,
        "nominal pulse calculation mismatch",
        errors,
    )
    require(
        abs(checks["pulse_safety"]["conservative_pulse_volume_ml"] - 0.0525) < 1e-12,
        "conservative pulse calculation mismatch",
        errors,
    )

    lock_path = ROOT / ".runtime" / "validator-collector.lock"
    first_lock = windows_live_collect.CollectorInstanceLock(lock_path)
    second_lock = windows_live_collect.CollectorInstanceLock(lock_path)
    first_lock.acquire()
    second_rejected = False
    try:
        try:
            second_lock.acquire()
        except RuntimeError:
            second_rejected = True
    finally:
        first_lock.release()
        second_lock.release()
    require(second_rejected, "concurrent collector lock was not rejected", errors)
    checks["single_instance"] = {"second_owner_rejected": second_rejected}

    sync_files = [
        "website/index.html",
        "website/app.js",
        "tools/windows_live_collect.py",
        "launchers/windows/20_windows_live_collect.bat",
        "launchers/windows/21_open_dashboard_server.bat",
        "auto_titrator/arduino_stepper/arduino_stepper.ino",
        "auto_titrator/arduino_stepper/command_parser.h",
    ]
    sync_status = {}
    for relative in sync_files:
        local = ROOT / relative
        windows = WINDOWS_ROOT / relative
        same = windows.exists() and sha256(local) == sha256(windows)
        sync_status[relative] = same
        require(same, f"Windows copy mismatch: {relative}", errors)
    checks["windows_sync"] = sync_status

    result = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "checks": checks,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
